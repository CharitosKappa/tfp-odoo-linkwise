import streamlit as st
import pandas as pd
import json

st.set_page_config(page_title="TFP: Odoo x Linkwise Order Validator", layout="wide")
st.title("📦 TFP | Odoo x Linkwise - Order Validator")

st.markdown("""
Ανέβασε 2 αρχεία:
- ERP (Sales Order)
- Linkwise (Pending ή Συγκεντρωτικό)
""")

erp_file = st.file_uploader("📤 Upload ERP αρχείο (Sales Order)", type=["xlsx"], key="erp")
linkwise_file = st.file_uploader("📤 Upload Linkwise αρχείο", type=["xlsx"], key="linkwise")

if erp_file and linkwise_file:
    try:
        # === Διαβάζουμε τα αρχεία ===
        erp_df = pd.read_excel(erp_file)
        linkwise_df = pd.read_excel(linkwise_file)

        # === Καθαρισμός Shopify Order Id ===
        erp_df["Shopify Order Id"] = erp_df["Shopify Order Id"].ffill().astype(str).str.replace(".0", "", regex=False).str.strip()

        # === Fill-down για λοιπές στήλες ===
        erp_df[["Customer", "Handling Status", "Status"]] = erp_df[["Customer", "Handling Status", "Status"]].ffill()

        # === Καθαρισμός Advertiser Id ===
        linkwise_df["Advertiser Id"] = linkwise_df["Advertiser Id"].astype(str).str.replace(".0", "", regex=False).str.strip()

        # === Εξαγωγή Courier State ===
        def extract_courier_state_friendly(value):
            try:
                parsed = json.loads(value)
                return parsed["courier_vouchers"][0]["state_friendly"]
            except:
                return None

        if "Courier State" in erp_df.columns:
            erp_df["Courier State Friendly"] = erp_df["Courier State"].apply(extract_courier_state_friendly)
        else:
            erp_df["Courier State Friendly"] = None

        # === Υπολογισμός STATUS ===
        statuses = []

        for _, row in linkwise_df.iterrows():
            order_id = row["Advertiser Id"]
            try:
                amount = float(row["Amount"])
            except:
                statuses.append("pending")
                continue

            related_rows = erp_df[erp_df["Shopify Order Id"] == order_id]

            if related_rows.empty:
                statuses.append("unmatched")
                continue

            # Κανόνες με σειρά προτεραιότητας

            # 1. Status in {canceled, cancelled, undelivered, undeliverd}
            if related_rows["Status"].str.lower().isin(["canceled", "cancelled", "undelivered", "undeliverd"]).any():
                statuses.append("cancel")
                continue

            # 2. Handling Status in {canceled, cancelled}
            if related_rows["Handling Status"].str.lower().isin(["canceled", "cancelled"]).any():
                statuses.append("cancel")
                continue

            # 3. Customer == Kalikatzarakis
            if related_rows["Customer"].str.lower().str.contains("kalikatzarakis").any():
                statuses.append("cancel")
                continue

            # 4. Courier Tracking Logic
            courier_state = related_rows["Courier State Friendly"].dropna().unique()
            if len(courier_state) > 0:
                state = courier_state[0].strip().lower()
                if state == "delivered":
                    statuses.append("valid")
                    continue
                elif state in ["returned to shipper", "canceled", "lost"]:
                    statuses.append("cancel")
                    continue
                else:
                    statuses.append("pending")
                    continue

            # 5. Handling Status == checked AND Status not in canceled
            if (related_rows["Handling Status"].str.lower() == "checked").any() and \
                not related_rows["Status"].str.lower().isin(["canceled", "cancelled", "undelivered", "undeliverd"]).any():
                statuses.append("pending")
                continue

            # 6. Υπολογισμός Ποσών ERP vs Linkwise
            filtered = related_rows[~related_rows["Order Lines/Product/Name"].str.lower().str.contains("courier", na=False)]

            line_values = []
            for _, line in filtered.iterrows():
                try:
                    untaxed = float(line["Order Lines/Untaxed Invoiced Amount"])
                    delivered_qty = float(line["Order Lines/Delivery Quantity"])
                    quantity = float(line.get("Order Lines/Product/Quantity", delivered_qty))

                    if quantity <= 0:
                        continue

                    if quantity == delivered_qty:
                        value = untaxed
                    else:
                        value = (untaxed / quantity) * delivered_qty
                    line_values.append(value)
                except:
                    continue

            erp_total = sum(line_values)

            if abs(erp_total - amount) <= 0.01:
                statuses.append("cancel")
            else:
                rel_diff = abs(erp_total - amount) / amount if amount != 0 else 0
                if rel_diff <= 0.01:
                    statuses.append("valid")
                else:
                    statuses.append(f"valid - σωστό ποσό: {erp_total:.2f}€")

        # === Προσθήκη στήλης Status ===
        linkwise_df["Status"] = statuses

        # === Export αρχείο ===
        export_filename = "TFP_Linkwise_Validated.xlsx"
        linkwise_df.to_excel(export_filename, index=False)

        st.success("✅ Ολοκληρώθηκε η επεξεργασία.")
        with open(export_filename, "rb") as f:
            st.download_button("📥 Κατέβασε το αρχείο", f, file_name=export_filename)

    except Exception as e:
        st.error(f"❌ Σφάλμα κατά την επεξεργασία: {e}")
