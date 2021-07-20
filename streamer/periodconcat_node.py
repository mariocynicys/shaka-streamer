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

"""Concatenates inputs into periods by creating a master DASH/HLS file."""

import os
import re
import time
from typing import List
from xml.etree import ElementTree
from streamer import __version__
from streamer.node_base import ProcessStatus, ThreadedNodeBase
from streamer.packager_node import PackagerNode
from streamer.pipeline_configuration import PipelineConfig, ManifestFormat
from streamer.output_stream import AudioOutputStream, VideoOutputStream
from streamer.m3u8_concater import HLSConcater


class PeriodConcatNode(ThreadedNodeBase):
  """A node that concatenates multiple DASH manifests and/or HLS playlists
  when the input is a multiperiod_inputs_list.
  """
  
  def __init__(self,
               pipeline_config: PipelineConfig,
               packager_nodes: List[PackagerNode],
               output_dir: str) -> None:
    """Stores all relevant information needed for the period concatenation."""
    super().__init__(thread_name='periodconcat', continue_on_exception=False, sleep_time=3)
    self._pipeline_config = pipeline_config
    self._output_dir = output_dir
    self._packager_nodes: List[PackagerNode] = packager_nodes
    
    # know whether the first period has video and audio or not.
    fp_has_vid, fp_has_aud = False, False
    for output_stream in packager_nodes[0].output_streams:
      if isinstance(output_stream, VideoOutputStream):
        fp_has_vid = True
      elif isinstance(output_stream, AudioOutputStream):
        fp_has_aud = True
    
    for i, packager_node in enumerate(self._packager_nodes):
      has_vid, has_aud = False, False
      for output_stream in packager_node.output_streams:
        if isinstance(output_stream, VideoOutputStream):
          has_vid = True
        elif isinstance(output_stream, AudioOutputStream):
          has_aud = True
      if has_vid != fp_has_vid or has_aud != fp_has_aud:
        # Overwrite the start and the stop methods.
        setattr(self, 'start', lambda: None)
        setattr(self, 'stop', lambda _=None: None)
        print("\nWARNING: Stopping period concatenation.")
        print("Period#{} has {}video and has {}audio while Period#1 "
              "has {}video and has {}audio.".format(i + 1, 
                                                    "" if has_vid else "no ",
                                                    "" if has_aud else "no ",
                                                    "" if fp_has_vid else "no ",
                                                    "" if fp_has_aud else "no "))
        print("\nHINT:\n\tBe sure that either all the periods have video or all do not,\n"
              "\tand all the periods have audio or all do not, i.e. don't mix videoless\n"
              "\tperiods with other periods that have video that is for the concatenation\n"
              "\tto be performed successfully.\n")
        time.sleep(5)
        break
  
  def _thread_single_pass(self) -> None:
    """Watches all the PackagerNode(s), if at least one of them is running it skips this
    _thread_single_pass, if all of them are finished, it starts period concatenation, if one of
    them is errored, it raises a RuntimeError.
    """
    
    for i, packager_node in enumerate(self._packager_nodes):
      status = packager_node.check_status()
      if status == ProcessStatus.Running:
        return
      elif status == ProcessStatus.Errored:
        raise RuntimeError(
          'Concatenation is stopped due '
          'to an error in PackagerNode#{}.'.format(i + 1))
    
    if ManifestFormat.DASH in self._pipeline_config.manifest_format:
      self._dash_concat()
      
    if ManifestFormat.HLS in self._pipeline_config.manifest_format:
      self._hls_concat()
    
    self._status = ProcessStatus.Finished
  
  def _dash_concat(self) -> None:
    """Concatenates multiple single-period DASH manifests into one multi-period DASH manifest."""
    
    def find(elem: ElementTree.Element, *args: str) -> ElementTree.Element:
      """A better interface for the Element.find() method.
      Use it only if it is guaranteed that the element we are searching for is inside,
      Otherwise it will raise an AssertionError."""
      
      full_path = '/'.join(['shaka-live:' + tag for tag in args])
      child_elem =  elem.find(full_path, {'shaka-live': default_dash_namespace})
      
      # elem.find() returns either an ElementTree.Element or None.
      assert child_elem is not None, 'Unable to find: {} using the namespace: {}'.format(
        full_path, default_dash_namespace)
      return child_elem
    
    # Periods that are going to be collected from different MPD files.
    periods: List[ElementTree.Element] = []
    
    # Get the root of an MPD file that we will concatenate periods into.
    concat_mpd = ElementTree.ElementTree(file=os.path.join(
      self._packager_nodes[0].output_dir,
      self._pipeline_config.dash_output)).getroot()
    
    # Get the default namespace.
    namespace_matches = re.search('\{([^}]*)\}', concat_mpd.tag)
    assert namespace_matches is not None, 'Unable to find the default namespace.'
    default_dash_namespace = namespace_matches.group(1)
    
    # Remove the 'mediaPresentationDuration' attribute.
    concat_mpd.attrib.pop('mediaPresentationDuration')
    # Remove the Period element in that MPD element.
    concat_mpd.remove(find(concat_mpd, 'Period'))
    
    for packager_node in self._packager_nodes:
      
      mpd = ElementTree.ElementTree(file=os.path.join(
        packager_node.output_dir,
        self._pipeline_config.dash_output)).getroot()
      period = find(mpd, 'Period')
      period.attrib['duration'] = mpd.attrib['mediaPresentationDuration']
      
      # A BaseURL that will have the relative path to media file.
      base_url = ElementTree.Element('BaseURL')
      base_url.text = os.path.relpath(packager_node.output_dir, self._output_dir) + '/'
      period.insert(0, base_url)
        
      periods.append(period)
    
    # Add the periods collected from all the files.
    concat_mpd.extend(periods)
    
    # Write the period concat to the output_dir.
    with open(os.path.join(
        self._output_dir,
        self._pipeline_config.dash_output), 'w') as master_dash:
      
      contents = "<?xml version='1.0' encoding='UTF-8'?>\n"
      # TODO: Add Shaka-Packager version to this xml comment.
      contents += "<!--Generated with https://github.com/google/shaka-packager -->\n"
      contents += "<!--Made Multi-Period with https://github.com/google/shaka-streamer version {} -->\n".format(__version__)
      
      # xml.ElementTree replaces the default namespace with 'ns0'.
      # Register the DASH namespace back as the defualt namespace before converting to string.
      ElementTree.register_namespace('', default_dash_namespace)
      
      # xml.etree.ElementTree already have an ElementTree().write() method,
      # but it won't allow putting comments at the begining of the file.
      contents += ElementTree.tostring(element=concat_mpd, encoding='unicode')
      master_dash.write(contents)
  
  def _hls_concat(self) -> None:
    """Concatenates multiple HLS playlists using #EXT-X-DISCONTINUITY."""
    
    # Initialize the HLS concater with a sample Master HLS playlist and
    # the output direcotry of the concatenated playlists.
    hls_concater = HLSConcater(os.path.join(self._packager_nodes[0].output_dir,
                                            self._pipeline_config.hls_output),
                               self._output_dir)
    
    for packager_node in self._packager_nodes:
      hls_concater.add(os.path.join(packager_node.output_dir,
                                    self._pipeline_config.hls_output))
    
    # Start the period concatenation.
    hls_concater.concat()
    
    # Write the concatenated playlists in the output directory passed while
    # constructing a concater instance.
    hls_concater.write(self._pipeline_config.hls_output,
                       'Concatenated with https://github.com/google/shaka-streamer'
                       ' version {}'.format(__version__))