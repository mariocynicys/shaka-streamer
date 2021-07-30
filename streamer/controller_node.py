# Copyright 2019 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Top-level module API.

If you'd like to import Shaka Streamer as a Python module and build it into
your own application, this is the top-level API you can use for that.  You may
also want to look at the source code to the command-line front end script
`shaka-streamer`.
"""


import os
import re
import shutil
import string
import subprocess
import sys
import tempfile
import uuid

from typing import Any, Dict, List, Optional, Tuple, Union
from streamer.cloud_node import CloudNode
from streamer.bitrate_configuration import BitrateConfig, AudioChannelLayout, VideoResolution
from streamer.external_command_node import ExternalCommandNode
from streamer.input_configuration import InputConfig, InputType, MediaType, Input
from streamer.node_base import NodeBase, ProcessStatus
from streamer.output_stream import AudioOutputStream, OutputStream, TextOutputStream, VideoOutputStream
from streamer.packager_node import PackagerNode
from streamer.pipeline_configuration import PipelineConfig, StreamingMode
from streamer.transcoder_node import TranscoderNode
from streamer.periodconcat_node import PeriodConcatNode
from streamer.winfifo import WinFIFO


class ControllerNode(object):
  """Controls all other nodes and manages shared resources."""

  def __init__(self) -> None:
    global_temp_dir = tempfile.gettempdir()

    # The docs state that if any of prefix, suffix, or dir are specified, all
    # must be specified (and not None).  Create a temp dir of our own, inside
    # the global temp dir, and with a name that indicates who made it.
    self._temp_dir: str = tempfile.mkdtemp(
        dir=global_temp_dir, prefix='shaka-live-', suffix='')

    self._nodes: List[NodeBase] = []

  def __del__(self) -> None:
    # Clean up named pipes by removing the temp directory we placed them in.
    shutil.rmtree(self._temp_dir)

  def __enter__(self) -> 'ControllerNode':
    return self

  def __exit__(self, *unused_args) -> None:
    self.stop()

  def _create_pipe(self, suffix = '') -> str:
    """Create a uniquely-named named pipe in the node's temp directory.

    Args:
      suffix (str): An optional suffix added to the pipe's name.  Used to
                    indicate to the packager when it's getting a certain text
                    format in a pipe.
    Raises:
      RuntimeError: If the platform doesn't have mkfifo.
    Returns:
      The path to the named pipe, as a string.
    """
    # Since the tempfile module creates actual files, use uuid to generate a
    # filename, then call mkfifo to create the named pipe.
    unique_name = str(uuid.uuid4()) + suffix
    
    # For POSIX systems.
    if os.name == 'posix':
      path = os.path.join(self._temp_dir, unique_name)
      readable_by_owner_only = 0o600  # Unix permission bits
      os.mkfifo(path, mode=readable_by_owner_only) # type: ignore
    
    # New Technology, aka WindowsNT.
    elif os.name == 'nt':
      path = '-nt-shaka-' + unique_name
      WinFIFO(path).start()
    else:
      raise RuntimeError('Platform not supported.')
    
    return path

  def start(self, output_dir: str,
            input_config_dict: Dict[str, Any],
            pipeline_config_dict: Dict[str, Any],
            bitrate_config_dict: Dict[Any, Any] = {},
            bucket_url: Union[str, None] = None,
            check_deps: bool = True) -> 'ControllerNode':
    """Create and start all other nodes.

    :raises: `RuntimeError` if the controller has already started.
    :raises: :class:`streamer.configuration.ConfigError` if the configuration is
             invalid.
    """

    if self._nodes:
      raise RuntimeError('Controller already started!')

    if check_deps:
      # Check that ffmpeg version is 4.1 or above.
      _check_version('FFmpeg', ['ffmpeg', '-version'], (4, 1))

      # Check that ffprobe version (used for autodetect features) is 4.1 or
      # above.
      _check_version('ffprobe', ['ffprobe', '-version'], (4, 1))

      # Check that Shaka Packager version is 2.4.2 or above.
      _check_version('Shaka Packager', ['packager', '-version'], (2, 4, 2))

      if bucket_url:
        # Check that the Google Cloud SDK is at least v212, which introduced
        # gsutil 4.33 with an important rsync bug fix.
        # https://cloud.google.com/sdk/docs/release-notes
        # https://github.com/GoogleCloudPlatform/gsutil/blob/master/CHANGES.md
        # This is only required if the user asked for upload to cloud storage.
        _check_version('Google Cloud SDK', ['gcloud', '--version'], (212, 0, 0))


    if bucket_url:
      # If using cloud storage, make sure the user is logged in and can access
      # the destination, independent of the version check above.
      CloudNode.check_access(bucket_url)


    self._output_dir = output_dir
    # Check if the directory for outputted Packager files exists, and if it
    # does, delete it and remake a new one.
    if os.path.exists(self._output_dir):
      shutil.rmtree(self._output_dir)
    os.mkdir(self._output_dir)

    # Define resolutions and bitrates before parsing other configs.
    bitrate_config = BitrateConfig(bitrate_config_dict)

    # Now that the definitions have been parsed, register the maps of valid
    # resolutions and channel layouts so that InputConfig and PipelineConfig
    # can be validated accordingly.
    VideoResolution.set_map(bitrate_config.video_resolutions)
    AudioChannelLayout.set_map(bitrate_config.audio_channel_layouts)

    self._input_config = InputConfig(input_config_dict)
    self._pipeline_config = PipelineConfig(pipeline_config_dict)

    if self._input_config.inputs:
      # InputConfig contains inputs only.
      self._append_nodes_for_inputs_list(self._input_config.inputs)
    else:
      # InputConfig contains multiperiod_inputs_list only.
      # Create one Transcoder node and one Packager node for each period.
      for i, singleperiod in enumerate(self._input_config.multiperiod_inputs_list):
        sub_dir_name = 'period_' + str(i)
        self._append_nodes_for_inputs_list(singleperiod.inputs, sub_dir_name)

      if self._pipeline_config.streaming_mode == StreamingMode.VOD:
        packager_nodes = [node for node in self._nodes if isinstance(node, PackagerNode)]
        self._nodes.append(PeriodConcatNode(
          self._pipeline_config,
          packager_nodes,
          self._output_dir))

    if bucket_url:
      cloud_temp_dir = os.path.join(self._temp_dir, 'cloud')
      os.mkdir(cloud_temp_dir)

      packager_nodes = [node for node in self._nodes if isinstance(node, PackagerNode)]
      self._nodes.append(CloudNode(self._output_dir,
                                   bucket_url,
                                   cloud_temp_dir,
                                   packager_nodes,
                                   self.is_vod()))

    for node in self._nodes:
      node.start()
      
    return self

  def _append_nodes_for_inputs_list(self, inputs: List[Input],
               period_dir: Optional[str] = None) -> None:
    """A common method that creates Transcoder and Packager nodes for a list of Inputs passed to it.
    
    Args:
      inputs (List[Input]): A list of Input streams.
      period_dir (Optional[str]): A subdirectory name where a single period will be outputted to.
      If passed, this indicates that inputs argument is one period in a list of periods.
    """
    
    outputs: List[OutputStream] = []
    for input in inputs:
      # External command inputs need to be processed by an additional node
      # before being transcoded.  In this case, the input doesn't have a
      # filename that FFmpeg can read, so we generate an intermediate pipe for
      # that node to write to.  TranscoderNode will then instruct FFmpeg to
      # read from that pipe for this input.
      if input.input_type == InputType.EXTERNAL_COMMAND:
        command_output = self._create_pipe()
        writer_command_output = command_output
        reader_command_output = command_output
        if os.name == 'nt':
          writer_command_output = WinFIFO.WRITER_PREFIX + command_output
          reader_command_output = WinFIFO.READER_PREFIX + command_output
        self._nodes.append(ExternalCommandNode(
            input.name, writer_command_output))
        input.set_pipe(reader_command_output)

      if input.media_type == MediaType.AUDIO:
        for audio_codec in self._pipeline_config.audio_codecs:
          outputs.append(AudioOutputStream(self._create_pipe(),
                                           input,
                                           audio_codec,
                                           self._pipeline_config.channels))

      elif input.media_type == MediaType.VIDEO:
        for video_codec in self._pipeline_config.video_codecs:
          for output_resolution in self._pipeline_config.get_resolutions():
            # Only going to output lower or equal resolution videos.
            # Upscaling is costly and does not do anything.
            if input.get_resolution() < output_resolution:
              continue

            outputs.append(VideoOutputStream(self._create_pipe(),
                                             input,
                                             video_codec,
                                             output_resolution))

      elif input.media_type == MediaType.TEXT:
        if input.name.endswith('.vtt') or input.name.endswith('.ttml'):
          # If the input is a VTT or TTML file, pass it directly to the packager
          # without any intermediate processing or any named pipe.
          # TODO: Test TTML inputs
          text_pipe = None  # Bypass transcoder
        else:
          # Otherwise, the input is something like an mkv file with text tracks
          # in it.  These will be extracted by the transcoder and passed in a
          # pipe to the packager.
          text_pipe = self._create_pipe('.vtt')

        outputs.append(TextOutputStream(text_pipe, input))

    self._nodes.append(TranscoderNode(inputs,
                                      self._pipeline_config,
                                      outputs))

    output_dir = self._output_dir
    
    # If the inputs list was a period in multiperiod_inputs_list, create a nested directory
    # and put that period in it.
    if period_dir:
      output_dir = os.path.join(output_dir, period_dir)
      os.mkdir(output_dir)

    self._nodes.append(PackagerNode(self._pipeline_config,
                                    output_dir,
                                    outputs))

  def check_status(self) -> ProcessStatus:
    """Checks the status of all the nodes.

    If one node is errored, this returns Errored; otherwise if one node is running,
    this returns Running; this only returns Finished if all nodes are finished.
    If there are no nodes, this returns Finished.
    """
    if not self._nodes:
      return ProcessStatus.Finished

    value = max(node.check_status().value for node in self._nodes)
    return ProcessStatus(value)

  def stop(self) -> None:
    """Stop all nodes."""
    status = self.check_status()
    for node in self._nodes:
      node.stop(status)
    self._nodes = []

  def is_vod(self) -> bool:
    """Returns True if the pipeline is running in VOD mode.

    :rtype: bool
    """

    return self._pipeline_config.streaming_mode == StreamingMode.VOD

class VersionError(Exception):
  """A version error for one of Shaka Streamer's external dependencies.

  Raised when a dependency (like FFmpeg) is missing or not new enough to work
  with Shaka Streamer.  See also :doc:`prerequisites`.
  """

  pass

def _check_version(name: str,
                   command: List[str],
                   minimum_version: Union[Tuple[int, int], Tuple[int, int, int]]) -> None:
  min_version_string = '.'.join(str(x) for x in minimum_version)

  def make_error_string(problem):
    return '{0} {1}! Please install version {2} or higher of {0}.'.format(
        name, problem, min_version_string)

  try:
    version_string = str(subprocess.check_output(command))
  except (subprocess.CalledProcessError, OSError) as e:
    if isinstance(e, subprocess.CalledProcessError):
      print(e.stdout, file=sys.stderr)
    raise VersionError(make_error_string('not found')) from None

  # Matches two or more numbers (one or more digits each) separated by dots.
  # For example: 4.1.3 or 7.2 or 216.999.8675309
  version_match = re.search(r'[0-9]+(?:\.[0-9]+)+', version_string)

  if version_match:
    version = tuple([int(piece) for piece in version_match.group(0).split('.')])
    if version < minimum_version:
      raise VersionError(make_error_string('out of date'))
  else:
    raise VersionError(name + ' version could not be parsed!')
