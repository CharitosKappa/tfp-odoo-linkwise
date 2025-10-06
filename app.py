import streamlit as st
import pandas as pd
import json
import io

st.set_page_config(page_title="TFP x Linkwise – Order Validator", layout="wide")
st.title("🧾 TFP x Linkwise – Order Validator")

st.markdown(
    "✔️ Συμπλήρωση status για αρχεία Linkwise\n\n"
    "📌 Χρησιμοποιούνται τα πεδία `Handling Status` και `Courier State`\n"
)

# Ανέβασμα αρχείων
erp_file = st.file_uploader("Upload ERP αρχείο (Sales Order)", type=["xlsx"])
linkwise_file = st.file_uploader("Upload Linkwise αρχείο", type=["xlsx"])

if erp_file and linkwise_file:
    try:
        # Διαβάζουμε τα αρχεία
        erp_df_raw = pd.read_excel(erp_file)
        linkwise_df = pd.read_excel(linkwise_file)

        # Fill down τις βασικές στήλες
        erp_df = erp_df_raw.copy()
        erp_df[["Shopify Order Id", "Customer", "Handling Status"]] = erp_df[["Shopify Order Id", "Customer", "Handling Status"]].ffill()

        # Group by παραγγελία
        grouped_erp = erp_df.groupby("Shopify Order Id")

        status_results = []

        for _, row in linkwise_df.iterrows():
            advertiser_id = str(row.get("Advertiser Id")).strip()
            amount = float(row.get("Amount", 0))

            if advertiser_id not in grouped_erp.groups:
                status_results.append("unmatched")
                continue

            order_lines = grouped_erp.get_group(advertiser_id)

            # Εξαγωγή unique Handling Status
            handling_statuses = order_lines["Handling Status"].dropna().astype(str).str.lower().unique()
            courier_states_raw = order_lines["Courier State"].dropna().astype(str).tolist()

            # Κανόνας 1: Handling Status → cancel
            if any(status in ["canceled", "cancelled"] for status in handling_statuses):
                status_results.append("cancel")
                continue

            # Κανόνας 2: Courier Tracking State
            courier_status_found = False
            for c_raw in courier_states_raw:
                try:
                    parsed = json.loads(c_raw)
                    state = parsed["courier_vouchers"][0]["state_friendly"]
                    if state in ["Returned To Shipper", "Canceled", "Lost"]:
                        status_results.append("cancel")
                        courier_status_found = True
                        break
                    elif state == "Delivered":
                        status_results.append("valid")
                        courier_status_found = True
                        break
                except:
                    continue

            if courier_status_found:
                continue

            # Κανόνας 3: Handling Status = checked
            if "checked" in handling_statuses:
                status_results.append("pending")
                continue

            # Κανόνας 4: Έλεγχος ποσού
            product_lines = order_lines[~order_lines["Order Lines/Product/Name"].astype(str).str.contains("courier", case=False)]

            total = 0.0
            for _, line in product_lines.iterrows():
                try:
                    qty = float(line.get("Order Lines/Product/Quantity", 0))
                    delivered = float(line.get("Order Lines/Delivery Quantity", 0))
                    untaxed = float(line.get("Order Lines/Untaxed Invoiced Amount", 0))

                    if qty == 0:
                        continue
                    if qty == delivered:
                        line_value = untaxed
                    else:
                        unit_price = untaxed / qty
                        line_value = unit_price * delivered

                    total += line_value
                except:
                    continue

            erp_total = round(total, 2)
            diff = abs(erp_total - amount)

            if diff <= 0.01:
                status_results.append("cancel")
            elif amount != 0:
                rel_diff = diff / amount
                if rel_diff <= 0.01:
                    status_results.append("valid")
                else:
                    status_results.append(f"valid - σωστό ποσό: {erp_total:.2f}€")
            else:
                status_results.append("valid")

        # Ενημέρωση και export
        linkwise_df["Status"] = status_results

        output = io.BytesIO()
        with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
            linkwise_df.to_excel(writer, index=False, sheet_name="Validated")
        st.success("✅ Ολοκληρώθηκε η επεξεργασία.")
        st.download_button("📥 Κατέβασε το αρχείο", data=output.getvalue(), file_name="TFP_Linkwise_Validated.xlsx")

    except Exception as e:
        st.error(f"❌ Σφάλμα κατά την επεξεργασία: {e}")
