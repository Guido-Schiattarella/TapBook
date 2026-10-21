"""MODEL — data storage.

  user_store.py   users in the SQLite database (data_dir/tapbook.db)
  filesystem.py   users' folders and files
  pdf_store.py    reading/writing the notes inside the PDFs
  document.py     document open for editing (notifies the controller of changes)
  layouts.py      page layouts (lines, grid, dots) drawn into the PDF
  pictures.py     processing of the photos coming from the iPad (profile photo too)
  search_index.py document text for the search
  files.py        atomic writes and links, the same on Linux and Windows
  dbserver.py     old MariaDB database: only to copy its users into SQLite
"""
