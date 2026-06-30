from . import models
from . import controllers
from .hooks import post_init_hook

# NB: the historical "incompatible with appointment_google_calendar" guard was
# removed in v17.0.2.3.0 — this module now DEPENDS on appointment_google_calendar
# (it reuses that module's native 'google_meet' videocall source as the default
# for every Appointment Type; see models/appointment_type.py). The old REST
# 'google_meet_rest' source no longer claims the same key, so they coexist.
