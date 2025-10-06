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

erp_file = st.file_uploader("Upload ERP αρχείο (Sales Order)", type=["xlsx"])
linkwise_file = st.file_uploader("Upload Linkwise αρχείο", type=["xlsx"])

if erp_file and linkwise_file:
    try:
        erp_df_raw = pd.read_excel(erp_file)
        linkwise_df = pd.read_excel(linkwise_file)

        # Προεπεξεργασία ERP
        erp_df = erp_df_raw.copy()
        erp_df[["Shopify Order Id", "Customer", "Handling Status"]] = erp_df[
            ["Shopify Order Id", "Customer", "Handling Status"]
        ].ffill()

        erp_df["Shopify Order Id"] = erp_df["Shopify Order Id"].astype(str).str.strip()
        linkwise_df["Advertiser Id"] = linkwise_df["Advertiser Id"].astype(str).str.strip()
        linkwise_df["Amount"] = pd.to_numeric(linkwise_df["Amount"], errors="coerce").fillna(0)

        grouped_erp = erp_df.groupby("Shopify Order Id")
        available_order_ids = grouped_erp.groups.keys()

        status_results = []

        for _, row in linkwise_df.iterrows():
            advertiser_id = row["Advertiser Id"]
            amount = row["Amount"]

            if advertiser_id not in available_order_ids:
                status_results.append("unmatched")
                continue

            order_lines = grouped_erp.get_group(advertiser_id)
            handling_statuses = (
                order_lines["Handling Status"].dropna().astype(str).str.lower().unique()
            )
            courier_states_raw = (
                order_lines["Courier State"].dropna().astype(str).tolist()
            )

            # -------- Κανόνας 1: Handling Status ακύρωσης
            if any(s in ["canceled", "cancelled"] for s in handling_statuses):
                status_results.append("cancel")
                continue

            # -------- Κανόνας 2: Courier State με προτεραιότητα
            courier_status = None

            for raw in courier_states_raw:
                try:
                    parsed = json.loads(raw)
                    state = parsed["courier_vouchers"][0]["state_friendly"]
                    if state in ["Returned To Shipper", "Canceled", "Lost"]:
                        courier_status = "cancel"
                        break
                    elif state == "Delivered":
                        courier_status = "valid"
                except:
                    continue

            if courier_status == "cancel":
                status_results.append("cancel")
                continue
            elif courier_status == "valid":
                status_results.append("valid")
                continue

            # -------- Κανόνας 3: Handling Status = checked
            if "checked" in handling_statuses:
                status_results.append("pending")
                continue

            # -------- Κανόνας 4: Έλεγχος ποσού
            product_lines = order_lines[
                ~order_lines["Order Lines/Product/Name"]
                .astype(str)
                .str.contains("courier", case=False, na=False)
            ]

            erp_total = 0.0
            for _, line in product_lines.iterrows():
                try:
                    qty = pd.to_numeric(line.get("Order Lines/Product/Quantity", 0), errors="coerce")
                    delivered = pd.to_numeric(line.get("Order Lines/Delivery Quantity", 0), errors="coerce")
                    untaxed = pd.to_numeric(line.get("Order Lines/Untaxed Invoiced Amount", 0), errors="coerce")

                    if pd.isna(qty) or pd.isna(delivered) or pd.isna(untaxed):
                        continue
                    if qty == 0:
                        continue

                    if qty == delivered:
                        line_value = untaxed
                    else:
                        unit_price = untaxed / qty
                        line_value = unit_price * delivered

                    erp_total += line_value
                except:
                    continue

            erp_total = round(erp_total, 2)
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

        linkwise_df["Status"] = status_results

        output = io.BytesIO()
        with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
            linkwise_df.to_excel(writer, index=False, sheet_name="Validated")

        st.success("✅ Ολοκληρώθηκε η επεξεργασία.")
        st.download_button(
            "📥 Κατέβασε το αρχείο",
            data=output.getvalue(),
            file_name="TFP_Linkwise_Validated.xlsx",
        )

    except Exception as e:
        st.error(f"❌ Σφάλμα κατά την επεξεργασία: {e}")
