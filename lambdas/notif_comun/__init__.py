"""Código compartido por las Lambdas ``despachador``, ``conciliador`` y ``respaldo-correo``
(design.md §4.5; CC-REQ-108 a 114).

No importa ``cc_notificaciones`` (las Lambdas no empaquetan el servicio): la regla del horario y el
formato del schedule se copian aquí en su forma mínima y se mantienen iguales a las del servicio
(``servicios/horario.py`` y ``scheduler.py``).
"""
