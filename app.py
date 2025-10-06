import streamlit as st
import pandas as pd
import numpy as np
import json
import io

st.set_page_config(page_title="Odoo x Linkwise - Order Validator")

st.title("📦 Odoo x Linkwise - Order Validator")

st.markdown("""
Ανέβασε τα δύο αρχεία:
1. **ERP (Sales Order)** – πολλαπλές γραμμές ανά παραγγελία
2. **Linkwise (Pending Sales)** – affiliate παραγγελίες

Θα παραχθεί νέο αρχείο με συμπληρωμένο το πεδίο **Status**.
""")

erp_file = st.file_uploader("⬆️ Upload ERP αρχείο (Sales Order)", type=["xlsx"])
linkwise_file = st.file_uploader("⬆️ Upload Linkwise αρχείο (Pending Sales)", type=["xlsx"])

if erp_file and linkwise_file:
    try:
        erp_df_raw = pd.read_excel(erp_file)
        linkwise_df = pd.read_excel(linkwise_file)

        # Fill-down για Order Id και Handling Status
        erp_df = erp_df_raw.copy()
        for col in ["Shopify Order Id", "Customer", "Handling Status", "Status"]:
            if col in erp_df.columns:
                erp_df[col] = erp_df[col].ffill()

        # Ομαδοποίηση ανά παραγγελία
        erp_orders = erp_df.groupby("Shopify Order Id")

        # Mapping Courier State → Status
        courier_mapping = {
            "Delivered": "valid",
            "Returned To Shipper": "cancel",
            "Canceled": "cancel",
            "Lost": "cancel"
        }

        results = []

        for _, row in linkwise_df.iterrows():
            advertiser_id = str(row["Advertiser Id"]).strip()
            try:
                order_lines = erp_orders.get_group(advertiser_id)
            except KeyError:
                results.append("unmatched")
                continue

            # Κανόνας 1: Courier State ή Handling Status
            handling_statuses = order_lines["Handling Status"].dropna().unique().astype(str).tolist()
            courier_states_raw = order_lines["Courier State"].dropna().astype(str).tolist()

            courier_status = None
            for val in courier_states_raw:
                if isinstance(val, str) and val.strip().startswith("{"):
                    try:
                        obj = json.loads(val)
                        state = obj.get("courier_vouchers", [{}])[0].get("state_friendly", None)
                        if state:
                            courier_status = courier_mapping.get(state, "pending")
                            if courier_status in ["valid", "cancel"]:
                                break
                    except Exception:
                        continue

            # Προτεραιότητα λογικής:
            if courier_status == "cancel":
                results.append("cancel")
                continue

            if any(h.lower() in ["cancelled", "canceled"] for h in handling_statuses):
                results.append("cancel")
                continue

            if "Customer" in order_lines.columns:
                if "kalikatzarakis" in str(order_lines["Customer"].iloc[0]).lower():
                    results.append("cancel")
                    continue

            if any(h.lower() == "checked" for h in handling_statuses):
                results.append("pending")
                continue

            if courier_status == "valid":
                results.append("valid")
                continue

            # Fallback: Έλεγχος ποσού
            order_lines = order_lines[~order_lines["Order Lines/Product/Name"].str.contains("Courier", na=False)]

            qty_col = "Order Lines/Delivery Quantity"
            amt_col = "Order Lines/Untaxed Invoiced Amount"

            qty = pd.to_numeric(order_lines[qty_col], errors="coerce").fillna(0)
            amt = pd.to_numeric(order_lines[amt_col], errors="coerce").fillna(0)

            line_values = qty * amt
            erp_total = line_values.sum()

            try:
                amount = float(row["Amount"])
            except:
                amount = 0.0

            diff = abs(erp_total - amount)

            if amount > 0 and diff >= amount - 0.01:
                results.append("cancel")
            elif amount > 0 and (diff / amount) <= 0.01:
                results.append("valid")
            else:
                results.append(f"valid - σωστό ποσό: {erp_total:.2f}€")

        output_df = linkwise_df.copy()
        output_df["Status"] = results

        st.success("✅ Η επεξεργασία ολοκληρώθηκε.")

        towrite = io.BytesIO()
        with pd.ExcelWriter(towrite, engine="xlsxwriter") as writer:
            output_df.to_excel(writer, index=False)
        towrite.seek(0)

        st.download_button(
            label="📥 Κατέβασε το αρχείο με τα αποτελέσματα",
            data=towrite,
            file_name="TFP_Linkwise_Validated.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

    except Exception as e:
        st.error(f"❌ Σφάλμα κατά την επεξεργασία: {e}")
