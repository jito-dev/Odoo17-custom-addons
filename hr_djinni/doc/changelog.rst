.. _changelog:

Changelog
=========

`17.0.1.0.5`
------------

- Fix crash when syncing a vacancy without a quiz: the create/sync wizard no
  longer calls quiz creation on an empty ``djinni.quiz`` record
  (``Expected singleton: djinni.quiz()``).

`17.0.1.0.4`
------------

- Surface Djinni API client errors (400/403/409/422): the rejection reason from
  the API response body is now shown to the user instead of a bare
  "Invalid Operation" / "400 Bad Request".

`17.0.1.0.3`
------------

- Fix vacancy/candidate sync: fall back to a stable name for anonymous Djinni
  candidates so the required ``hr.applicant.name`` is always set.

`17.0.1.0.1`
------------

- Improve views.

`17.0.1.0.0`
------------

- Init version.


