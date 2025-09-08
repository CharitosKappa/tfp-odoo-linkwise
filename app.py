import streamlit as st
import pandas as pd
from modules.logic import process_linkwise_vs_erp
from modules.utils import download_excel

st.set_page_config(page_title="Odoo x Linkwise - Order Validator", layout="wide")
st.title("📦 Odoo x Linkwise – Order Validator")

mode = st.radio("Επέλεξε τύπο αρχείου προς έλεγχο:", ["📅 Εβδομαδιαίο αρχείο", "🗓️ Μηνιαίο συγκεντρωτικό"])

if mode == "📅 Εβδομαδιαίο αρχείο":
    linkwise_file = st.file_uploader("📤 Ανέβασε το αρχείο Linkwise (Pending Sales)", type=["xlsx"])
else:
    linkwise_file = st.file_uploader("📤 Ανέβασε το συγκεντρωτικό αρχείο Linkwise (χωρίς Status)", type=["xlsx"])

erp_file = st.file_uploader("📤 Ανέβασε το αρχείο ERP (Sales Order)", type=["xlsx"])

if linkwise_file and erp_file:
    with st.spinner("🔄 Επεξεργασία αρχείων..."):
        try:
            linkwise_df = pd.read_excel(linkwise_file)
            erp_df = pd.read_excel(erp_file)

            if "Status" not in linkwise_df.columns:
                linkwise_df["Status"] = ""

            result_df = process_linkwise_vs_erp(linkwise_df, erp_df)

            st.success("✅ Ολοκληρώθηκε η επεξεργασία.")
            st.dataframe(result_df)

            excel_bytes = download_excel(result_df)
            st.download_button(
                label="📥 Κατέβασε το τελικό αρχείο",
                data=excel_bytes,
                file_name="Linkwise_Results.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
        except Exception as e:
            st.error(f"❌ Παρουσιάστηκε σφάλμα: {e}")
else:
    st.info("⏳ Περιμένω να ανεβάσεις και τα δύο αρχεία...")
