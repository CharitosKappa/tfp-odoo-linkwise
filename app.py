
import streamlit as st
import pandas as pd
import numpy as np
import json
import io

st.set_page_config(page_title="Odoo x Linkwise - Order Validator", layout="wide")
st.title("📦 Odoo x Linkwise - Order Validator")

def extract_courier_state(state_str):
    try:
        state_data = json.loads(state_str)
        vouchers = state_data.get("courier_vouchers", [])
        if vouchers and isinstance(vouchers, list):
            return vouchers[0].get("state_friendly", "").strip()
        return ""
    except Exception:
        return ""

def map_courier_state_to_status(state):
    if state == "Delivered":
        return "valid"
    elif state in {"Returned To Shipper", "Canceled", "Lost"}:
        return "cancel"
    return "pending"

def process_linkwise_vs_erp(linkwise_df, erp_df):
    fill_cols = ["Shopify Order Id", "Customer", "Handling Status", "Status"]
    for col in fill_cols:
        if col in erp_df.columns:
            erp_df[col] = erp_df[col].ffill()

    if "Courier State" in erp_df.columns:
        erp_df["Courier State Friendly"] = erp_df["Courier State"].apply(extract_courier_state)
    else:
        erp_df["Courier State Friendly"] = ""

    erp_df["Shopify Order Id"] = erp_df["Shopify Order Id"].astype(str)
    linkwise_df["Advertiser Id"] = linkwise_df["Advertiser Id"].astype(str)

    merged_df = pd.merge(
        linkwise_df,
        erp_df,
        how="left",
        left_on="Advertiser Id",
        right_on="Shopify Order Id",
        suffixes=("", "_erp")
    )

    statuses = []

    for _, row in merged_df.iterrows():
        handling_status = str(row.get("Handling Status", "")).lower()
        order_status = str(row.get("Status", "")).lower()
        customer = str(row.get("Customer", ""))
        courier_state = row.get("Courier State Friendly", "").strip()

        if order_status in {"canceled", "cancelled", "undelivered", "undeliverd"}:
            statuses.append("cancel")
            continue
        if handling_status in {"canceled", "cancelled"}:
            statuses.append("cancel")
            continue
        if customer.strip().lower() == "kalikatzarakis":
            statuses.append("cancel")
            continue

        if courier_state:
            statuses.append(map_courier_state_to_status(courier_state))
            continue

        if handling_status == "checked" and order_status not in {"canceled", "cancelled", "undelivered", "undeliverd"}:
            statuses.append("pending")
            continue

        order_id = row.get("Shopify Order Id", "")
        erp_lines = erp_df[erp_df["Shopify Order Id"] == order_id]
        erp_lines = erp_lines[~erp_lines["Order Lines/Product/Name"].str.contains("Courier", case=False, na=False)]

        line_values = []
        for _, line in erp_lines.iterrows():
            untaxed_amount = line["Order Lines/Untaxed Invoiced Amount"]
            line_values.append(untaxed_amount)

        erp_total = sum(line_values)
        linkwise_amount = row["Amount"]
        linkwise_amount = row["Amount"]

        if abs(erp_total - linkwise_amount) <= 0.01:
            statuses.append("cancel")
        else:
            relative_diff = abs(erp_total - linkwise_amount) / linkwise_amount
            if relative_diff <= 0.01:
                statuses.append("valid")
            else:
                statuses.append(f"valid - η σωστή τιμή είναι {erp_total:.2f}€")

    linkwise_df["Status"] = statuses
    return linkwise_df

uploaded_erp = st.file_uploader("📤 Upload ERP αρχείο (Sales Order)", type=["xlsx"], key="erp")
uploaded_linkwise = st.file_uploader("📤 Upload Linkwise αρχείο", type=["xlsx"], key="linkwise")

if uploaded_erp and uploaded_linkwise:
    try:
        erp_df = pd.read_excel(uploaded_erp)
        linkwise_df = pd.read_excel(uploaded_linkwise)

        output_df = process_linkwise_vs_erp(linkwise_df, erp_df)

        st.success("✅ Ολοκληρώθηκε η επεξεργασία.")
        st.dataframe(output_df)

        towrite = io.BytesIO()
        output_df.to_excel(towrite, index=False, engine="xlsxwriter")
        towrite.seek(0)

        st.download_button(
            label="📥 Κατέβασε το τελικό αρχείο",
            data=towrite,
            file_name="linkwise_validated_output.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
    except Exception as e:
        st.error(f"❌ Σφάλμα κατά την επεξεργασία: {str(e)}")
else:
    st.info("⬆️ Ανέβασε τα 2 απαραίτητα αρχεία για να συνεχίσεις.")
