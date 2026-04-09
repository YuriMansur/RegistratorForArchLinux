# Dev_192_168_10_10_OPC_Tags.py
# Auto-generated OPC UA tag constants

class Dev_192_168_10_10_OPC_Tags:
    values = "ns=2;s=Application.BurnAfterReading.values"
    inProcess = "ns=2;s=Application.Control.inProcess"
    End = "ns=2;s=Application.Control.End"


# Использование:
#   from tags import Dev_192_168_10_10_OPC_Tags
#   backend.read_node(server_id, Dev_192_168_10_10_OPC_Tags.Temperature)