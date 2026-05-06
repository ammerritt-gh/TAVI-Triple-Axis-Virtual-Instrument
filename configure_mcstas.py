import mcstasscript as ms
from pathlib import Path
import os

# Show yaml location
pkg = Path(ms.__file__).parent
yaml = pkg / "configuration.yaml"
print("YAML path:", yaml)
print("YAML exists:", yaml.exists())
if yaml.exists():
    print("YAML contents:")
    print(yaml.read_text())

# Set paths
c = ms.Configurator()
c.set_mcstas_path(r"C:\mcstas-3.6.14\lib")
c.set_mcrun_path(r"C:\mcstas-3.6.14\bin")

print("\nAfter Configurator:")
if yaml.exists():
    print(yaml.read_text())
else:
    print("YAML file not found after configuration")

# Manually test what ComponentReader sees
from mcstasscript.helper.component_reader import ComponentReader
print("Testing ComponentReader directly with C:\\mcstas-3.6.14\\lib ...")
reader = ComponentReader(r"C:\mcstas-3.6.14\lib", ".")
if "Progress_bar" in reader.component_path:
    print("SUCCESS - Progress_bar found at:", reader.component_path["Progress_bar"])
else:
    print("FAILED - Progress_bar not in component_path")
    print("Known components:", list(reader.component_path.keys())[:10])

# Now test via McStas_instr
print("\nTesting via McStas_instr...")
instr = ms.McStas_instr("test")
instr.add_component("origin", "Progress_bar", AT=[0, 0, 0])
print("SUCCESS")
