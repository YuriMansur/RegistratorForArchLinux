# Dev_192_168_10_10_OPC_Tags.py
# Auto-generated OPC UA tag constants

class Dev_192_168_10_10_OPC_Tags:
    rDTAT = "ns=2;s=Application.SensorsHandler.rDTAT"
    rDavDDA = "ns=2;s=Application.SensorsHandler.rDavDDA"
    rDavDDB = "ns=2;s=Application.SensorsHandler.rDavDDB"
    rDavDDB_kPa = "ns=2;s=Application.SensorsHandler.rDavDDB_kPa"
    rDavDDN1 = "ns=2;s=Application.SensorsHandler.rDavDDN1"
    rDavDDN2 = "ns=2;s=Application.SensorsHandler.rDavDDN2"
    rDavDDP1 = "ns=2;s=Application.SensorsHandler.rDavDDP1"
    rDavDDP1_1 = "ns=2;s=Application.SensorsHandler.rDavDDP1_1"
    rDavDDP2 = "ns=2;s=Application.SensorsHandler.rDavDDP2"
    rDavReserve1 = "ns=2;s=Application.SensorsHandler.rDavReserve1"
    rDavReserve2 = "ns=2;s=Application.SensorsHandler.rDavReserve2"
    rTempDT1 = "ns=2;s=Application.SensorsHandler.rTempDT1"
    rTempDT2 = "ns=2;s=Application.SensorsHandler.rTempDT2"
    rTempDTB = "ns=2;s=Application.SensorsHandler.rTempDTB"
    inProcess = "ns=2;s=Application.Control.inProcess"
    End = "ns=2;s=Application.Control.End"


# Использование:
#   from tags import Dev_192_168_10_10_OPC_Tags
#   backend.read_node(server_id, Dev_192_168_10_10_OPC_Tags.Temperature)