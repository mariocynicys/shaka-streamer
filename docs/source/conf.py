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
#
# Configuration file for the Sphinx documentation builder.  Generated by
# sphinx-quickstart and heavily customized.
#
# This file only contains a selection of the most common options. For a full
# list, see the documentation:
# http://www.sphinx-doc.org/en/master/config

# -- Path setup --------------------------------------------------------------

# If extensions (or modules to document with autodoc) are in another directory,
# add these directories to sys.path here. If the directory is relative to the
# documentation root, use os.path.abspath to make it absolute, like shown here.

# This adds the path to the project root, so that "streamer" can be found by
# the doc generator.
import os
import sys
ROOT = os.path.join(os.path.dirname(__file__), '..', '..')
sys.path.insert(0, os.path.abspath(ROOT))

# This imports certain types we will use directly in the customization at the
# bottom of the config file.
import docutils.nodes
import sphinx.addnodes
import streamer


# -- Project information -----------------------------------------------------

project = 'Shaka Streamer'
copyright = '2019, Google'
author = 'Google'

# The short X.Y version
version = '.'.join(streamer.VERSION.split('.')[0:2])
# The full version, including alpha/beta/rc tags
release = streamer.VERSION


# -- General configuration ---------------------------------------------------

# If your documentation needs a minimal Sphinx version, state it here.
#
# needs_sphinx = '1.0'

# Add any Sphinx extension module names here, as strings. They can be
# extensions coming with Sphinx (named 'sphinx.ext.*') or your custom
# ones.
extensions = [
    'sphinx.ext.autodoc',
    'sphinx.ext.viewcode',
]

# Add any paths that contain templates here, relative to this directory.
templates_path = []

# The suffix(es) of source filenames.
# You can specify multiple suffix as a list of string:
#
# source_suffix = ['.rst', '.md']
source_suffix = '.rst'

# The master toctree document.
master_doc = 'index'

# The language for content autogenerated by Sphinx. Refer to documentation
# for a list of supported languages.
#
# This is also used if you do content translation via gettext catalogs.
# Usually you set "language" from the command line for these cases.
language = None

# List of patterns, relative to source directory, that match files and
# directories to ignore when looking for source files.
# This pattern also affects html_static_path and html_extra_path.
exclude_patterns = []

# The name of the Pygments (syntax highlighting) style to use.
pygments_style = None


# -- Options for HTML output -------------------------------------------------

# The theme to use for HTML and HTML Help pages.  See the documentation for
# a list of builtin themes.
#
html_theme = 'alabaster'

# Theme options are theme-specific and customize the look and feel of a theme
# further.  For a list of options available for each theme, see the
# documentation.
#
# html_theme_options = {}

# Add any paths that contain custom static files (such as style sheets) here,
# relative to this directory. They are copied after the builtin static files,
# so a file named "default.css" will overwrite the builtin "default.css".
html_static_path = []

# Custom sidebar templates, must be a dictionary that maps document names
# to template names.
#
# The default sidebars (for documents that don't match any pattern) are
# defined by theme itself.  Builtin themes are using these templates by
# default: ``['localtoc.html', 'relations.html', 'sourcelink.html',
# 'searchbox.html']``.
#
# html_sidebars = {}


# -- Options for HTMLHelp output ---------------------------------------------

# Output file base name for HTML help builder.
htmlhelp_basename = 'ShakaStreamerDoc'


# -- Options for LaTeX output ------------------------------------------------

latex_elements = {
    # The paper size ('letterpaper' or 'a4paper').
    #
    # 'papersize': 'letterpaper',

    # The font size ('10pt', '11pt' or '12pt').
    #
    # 'pointsize': '10pt',

    # Additional stuff for the LaTeX preamble.
    #
    # 'preamble': '',

    # Latex figure (float) alignment
    #
    # 'figure_align': 'htbp',
}

# Grouping the document tree into LaTeX files. List of tuples
# (source start file, target name, title,
#  author, documentclass [howto, manual, or own class]).
latex_documents = [
    (master_doc, 'ShakaStreamer.tex', 'Shaka Streamer Documentation',
     'Google', 'manual'),
]


# -- Options for manual page output ------------------------------------------

# One entry per manual page. List of tuples
# (source start file, name, description, authors, manual section).
man_pages = [
    (master_doc, 'shakastreamer', 'Shaka Streamer Documentation',
     [author], 1)
]


# -- Options for Texinfo output ----------------------------------------------

# Grouping the document tree into Texinfo files. List of tuples
# (source start file, target name, title, author,
#  dir menu entry, description, category)
texinfo_documents = [
    (master_doc, 'ShakaStreamer', 'Shaka Streamer Documentation',
     author, 'ShakaStreamer', 'One line description of project.',
     'Miscellaneous'),
]


# -- Options for Epub output -------------------------------------------------

# Bibliographic Dublin Core info.
epub_title = project

# The unique identifier of the text. This can be a ISBN number
# or the project homepage.
#
# epub_identifier = ''

# A unique identification for the text.
#
# epub_uid = ''

# A list of files that should not be packed into the epub file.
epub_exclude_files = ['search.html']


# -- Extension configuration -------------------------------------------------

# Default settings for autdoc.
autodoc_default_flags = [
  'members',           # Document members,
  'undoc-members',     # including those with no docstring,
  'inherited-members', # and inherited members.
  'show-inheritance',  # Show details on inheritance.
]

# By default, put everything in the docs in the same order it appears in the
# source.
autodoc_member_order = 'bysource'


# A map from fully-qualified field names to the Field object that represents
# what type it accepts.
name_to_type_map = {}

def process_signature(app, _, name, obj, *other_ignored_args):
  """A callback for each signature in the docs.

  Builds a map of the various config field names to their Field objects so that
  we can later override the documentation for those types."""

  if isinstance(obj, streamer.configuration.Field):
    name_to_type_map[name] = obj

def get_first_child(node, type):
  """Return the first child of |node| that has type |type|."""

  index = node.first_child_matching_class(type)
  return node[index]

def process_doc_nodes(app, doctree, fromdocname):
  """A callback invoked when the documentation is built.

  We use this opportunity to override the docs for config Field objects to
  indicate a human-readable type instead of just "Field"."""

  # Go through all the signature nodes.
  for node in doctree.traverse(sphinx.addnodes.desc_signature):
    # Find the ones that refer to "Field" objects.
    if 'streamer.configuration.Field' in str(node):
      # Get the name of the thing.
      name = node['names'][0]
      if name.startswith('streamer.configuration.Field'):
        # Skip the Field object itself and all its members/attributes.
        continue

      # Find the node that contains the type text.
      annotation = get_first_child(node, sphinx.addnodes.desc_annotation)
      text = get_first_child(annotation, docutils.nodes.Text)

      # Replace "Field" with more descriptive text.
      field_object = name_to_type_map[name]
      replacement_text = ': ' + field_object.get_type_name()
      annotation.replace(text, docutils.nodes.Text(
          data=replacement_text, rawsource=replacement_text))

def setup(app):
  """Called by Sphinx on startup.

  Allows us to install callbacks for certain events and customize the docs."""

  app.connect('autodoc-process-signature', process_signature)
  app.connect('doctree-resolved', process_doc_nodes)

