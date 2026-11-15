"""Stack local de desarrollo: todo el sistema en la máquina, sin AWS real (docs/local.md).

Nada de este paquete se empaqueta para AWS: vive solo en ``scripts/`` y el proveedor de
identidad de desarrollo se niega a arrancar si ``CC_AMBIENTE`` no es ``local``.
"""
