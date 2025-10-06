import streamlit as st
import pandas as pd
import json
import io

st.set_page_config(page_title="Odoo x Linkwise Validator", layout="centered")

st.title("📦 Odoo x Linkwise - Order Validator")

st.markdown(
    "✅ Ανέβασε τα 2 αρχεία (ERP πωλήσεων + Linkwise παραγγελιών) για να παραχθεί το απαντητικό αρχείο με status:"
)

erp_file = st.file_uploader("🔹 Upload ERP αρχείο (Sales Order)", type=["xlsx"])
linkwise_file = st.file_uploader("🔹 Upload Linkwise αρχείο", type=["xlsx"])

if erp_file and linkwise_file:
    try:
        # --- Διαβάζουμε τα αρχεία ---
        erp_df = pd.read_excel(erp_file)
        linkwise_df = pd.read_excel(linkwise_file)

        # --- Συμπλήρωση κενών Shopify Order Id / Customer / Status / Handling Status ---
        erp_df[["Shopify Order Id", "Customer", "Status", "Handling Status"]] = erp_df[
            ["Shopify Order Id", "Customer", "Status", "Handling Status"]
        ].ffill()

        # --- Δημιουργία πίνακα με unique ERP orders ---
        erp_orders = erp_df.groupby("Shopify Order Id")

        status_results = []

        for idx, row in linkwise_df.iterrows():
            advertiser_id = str(row.get("Advertiser Id")).strip()
            amount = row.get("Amount", 0)

            if advertiser_id not in erp_df["Shopify Order Id"].astype(str).str.strip().values:
                status_results.append("unmatched")
                continue

            erp_order_lines = erp_df[erp_df["Shopify Order Id"].astype(str).str.strip() == advertiser_id]

            # Κανόνες
            status_erp = str(erp_order_lines["Status"].iloc[0]).strip().lower()
            handling_status = str(erp_order_lines["Handling Status"].iloc[0]).strip().lower()
            customer = str(erp_order_lines["Customer"].iloc[0]).strip().lower()

            # Courier state parsing
            courier_raw = erp_order_lines["Courier State"].dropna().values
            courier_status = None
            if len(courier_raw) > 0:
                try:
                    first_json = json.loads(courier_raw[0])
                    courier_status = (
                        first_json.get("courier_vouchers", [{}])[0].get("state_friendly", None)
                    )
                except Exception:
                    pass

            # --- Rule 1: Courier State based ---
            if courier_status in ["Returned To Shipper", "Canceled", "Lost"]:
                status_results.append("cancel")
                continue
            if courier_status == "Delivered":
                status_results.append("valid")
                continue

            # --- Rule 2: Handling Status ---
            if handling_status in ["cancelled", "canceled"]:
                status_results.append("cancel")
                continue

            # --- Rule 3: Customer is Kalikatzarakis ---
            if "kalikatzarakis" in customer.lower():
                status_results.append("cancel")
                continue

            # --- Rule 4: Pending if checked (handling) but not canceled status ---
            if handling_status == "checked" and status_erp not in [
                "canceled",
                "cancelled",
                "undelivered",
                "undeliverd",
            ]:
                status_results.append("pending")
                continue

            # --- Rule 5: Amount Check ---
            erp_lines = erp_order_lines[
                ~erp_order_lines["Order Lines/Product/Name"].str.contains("courier", case=False, na=False)
            ]

            # Ensure numeric
            erp_lines["Untaxed"] = pd.to_numeric(
                erp_lines["Order Lines/Untaxed Invoiced Amount"], errors="coerce"
            )
            erp_lines["Qty"] = pd.to_numeric(
                erp_lines["Order Lines/Delivery Quantity"], errors="coerce"
            )

            line_values = erp_lines["Untaxed"] * erp_lines["Qty"]
            erp_total = round(line_values.sum(), 2)

            # Έλεγχος αν amount δεν είναι αριθμός
            try:
                amount = float(amount)
            except:
                amount = 0.0

            if abs(erp_total - amount) <= 0.01:
                status_results.append("cancel")
            elif amount > 0 and abs(erp_total - amount) / amount <= 0.01:
                status_results.append("valid")
            else:
                status_results.append(f"valid - σωστό ποσό: {erp_total:.2f}€")

        linkwise_df["Status"] = status_results

        # --- Εξαγωγή αποτελέσματος ---
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
            linkwise_df.to_excel(writer, index=False)
        output.seek(0)

        st.success("✅ Ολοκληρώθηκε η επεξεργασία.")
        st.download_button("📥 Κατέβασε το αρχείο αποτελεσμάτων", output, file_name="TFP_Linkwise_Validated.xlsx")

    except Exception as e:
        st.error(f"❌ Σφάλμα κατά την επεξεργασία: {e}")
