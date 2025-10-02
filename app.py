
import streamlit as st
import pandas as pd
import json

st.set_page_config(page_title="TFP: Linkwise x ERP Order Validator", layout="wide")
st.title("📦 TFP | Odoo x Linkwise - Order Validator")

st.markdown("""Ανέβασε 2 αρχεία:
- ERP (Sales Order)
- Linkwise (Pending/Monthly Sales)
""")

erp_file = st.file_uploader("Upload ERP αρχείο (Sales Order)", type=["xlsx"], key="erp")
linkwise_file = st.file_uploader("Upload Linkwise αρχείο", type=["xlsx"], key="linkwise")

if erp_file and linkwise_file:
    try:
        erp_df = pd.read_excel(erp_file)
        linkwise_df = pd.read_excel(linkwise_file)

        # Προεπεξεργασία ID (αφαίρεση .0)
        def clean_id(val):
            return str(val).strip().replace(".0", "")

        erp_df["Shopify Order Id"] = erp_df["Shopify Order Id"].ffill().apply(clean_id)
        linkwise_df["Advertiser Id"] = linkwise_df["Advertiser Id"].astype(str).apply(clean_id)

        # Fill-down για Customer, Handling Status, Status
        erp_df[["Customer", "Handling Status", "Status"]] = erp_df[
            ["Customer", "Handling Status", "Status"]
        ].ffill()

        # Εξαγωγή state_friendly από Courier State
        def extract_friendly_state(row):
            try:
                raw = row.get("Courier State")
                if pd.isna(raw):
                    return ""
                data = json.loads(raw)
                return data["courier_vouchers"][0].get("state_friendly", "")
            except:
                return ""

        erp_df["Courier State Friendly"] = erp_df.apply(extract_friendly_state, axis=1)

        statuses = []
        for _, row in linkwise_df.iterrows():
            order_id = row["Advertiser Id"]
            amount = row["Amount"]

            erp_lines = erp_df[erp_df["Shopify Order Id"] == order_id]

            if erp_lines.empty:
                statuses.append("pending")
                continue

            if erp_lines["Status"].str.lower().isin(["canceled", "cancelled", "undelivered", "undeliverd"]).any():
                statuses.append("cancel")
                continue

            if erp_lines["Handling Status"].str.lower().isin(["canceled", "cancelled"]).any():
                statuses.append("cancel")
                continue

            if erp_lines["Customer"].astype(str).str.lower().str.contains("kalikatzarakis").any():
                statuses.append("cancel")
                continue

            courier_state = str(erp_lines["Courier State Friendly"].iloc[0]).strip().lower()
            if courier_state in ["returned to shipper", "canceled", "lost"]:
                statuses.append("cancel")
                continue
            elif courier_state == "delivered":
                statuses.append("valid")
                continue

            if (
                erp_lines["Handling Status"].str.lower().eq("checked").any()
                and not erp_lines["Status"].str.lower().isin(["canceled", "cancelled", "undelivered", "undeliverd"]).any()
            ):
                statuses.append("pending")
                continue

            valid_lines = erp_lines[~erp_lines["Order Lines/Product/Name"].str.lower().str.contains("courier", na=False)]

            line_values = []
            for _, line in valid_lines.iterrows():
                try:
                    untaxed_amount = line["Order Lines/Untaxed Invoiced Amount"]
                    delivered_qty = line["Order Lines/Delivery Quantity"]
                    quantity = line.get("Order Lines/Product/Quantity", delivered_qty)

                    if quantity == delivered_qty:
                        value = untaxed_amount
                    else:
                        value = (untaxed_amount / quantity) * delivered_qty if quantity != 0 else 0
                    line_values.append(value)
                except:
                    continue

            erp_total = sum(line_values)

            if abs(erp_total - amount) <= 0.01:
                statuses.append("cancel")
            else:
                diff_ratio = abs(erp_total - amount) / amount if amount != 0 else 0
                if diff_ratio <= 0.01:
                    statuses.append("valid")
                else:
                    statuses.append(f"valid - σωστό ποσό: {erp_total:.2f}€")

        linkwise_df["Status"] = statuses

        output_filename = "TFP_Linkwise_Validated.xlsx"
        linkwise_df.to_excel(output_filename, index=False)

        with open(output_filename, "rb") as f:
            st.success("✅ Ολοκληρώθηκε η επεξεργασία.")
            st.download_button("📥 Κατέβασε το αρχείο αποτελεσμάτων", f, file_name=output_filename)

    except Exception as e:
        st.error(f"❌ Σφάλμα κατά την επεξεργασία: {e}")
