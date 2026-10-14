import requests
from config import BEA_API_KEY

BEA = "https://apps.bea.gov/api/data/"

for tbl in ["T30100", "T30300"]:
    params = {
        "UserID": BEA_API_KEY,
        "method": "GetData",
        "DataSetName": "NIPA",
        "TableName": tbl,
        "Frequency": "A",
        "Year": "2024,2025",
        "ResultFormat": "JSON",
    }
    r = requests.get(BEA, params=params, timeout=60)
    data = r.json()
    res = data["BEAAPI"]["Results"]
    if "Error" in res:
        print(f"{tbl}: ERROR — {res['Error']}")
        continue
    rows = res.get("Data", [])
    print(f"\n=== {tbl} ===")
    for row in rows:
        ld = row.get("LineDescription", "")
        if "Net lending" in ld or "net lending" in ld.lower():
            print(f"{row['TimePeriod']}: {row['DataValue']} ({ld})")
