# Dev_192_168_10_10_OPC_Tags.py
# Auto-generated OPC UA tag constants

class Dev_192_168_10_10_OPC_Tags:
    inProcess = "ns=2;s=Application.Control.inProcess"
    End = "ns=2;s=Application.Control.End"
    ForUra = "ns=2;s=Application.TimeOfWork.ForUra"
    ForUra2 = "ns=2;s=Application.TimeOfWork.rForUra2"

# Использование:                 
#   from tags import Dev_192_168_10_10_OPC_Tags
#   backend.read_node(server_id, Dev_192_168_10_10_OPC_Tags.Temperature)