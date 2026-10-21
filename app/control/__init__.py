"""CONTROL (on the computer) — business logic.

  auth.py        login, sign-up, password and lock rules
  account.py     account from the web: profile photo, password change, deletion
  navigation.py  which view the interface must show (list or editor)
  library.py     document list (folders, new PDFs), search, trash
  editing.py     editing sessions: operations, undo/redo, autosave, conflicts
  geometry.py    eraser and lasso: which items a gesture touches or encloses
  shapes.py      recognition of geometric shapes
  errors.py      domain errors, turned into HTTP responses by the view

Controllers receive the requests of the view (in the iPad browser), use the
model and answer with the data and the view to show. They know nothing about HTML.
"""
