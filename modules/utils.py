from io import BytesIO
import pandas as pd

def download_excel(df):
    output = BytesIO()
    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        df.to_excel(writer, index=False, sheet_name="Results")
    output.seek(0)
    return output
