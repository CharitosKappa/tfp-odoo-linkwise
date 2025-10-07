import streamlit as st
import pandas as pd
import json
import io

st.set_page_config(page_title="Linkwise Sales Validator", layout="wide")
st.title("✅ Linkwise Validated Sales Generator")
st.markdown("version 2")

st.markdown("""
Ανεβάστε τα δύο απαραίτητα αρχεία Excel:
- **ERP Final Sales**
- **Linkwise Pending Sales**

Θα δημιουργηθεί ένα νέο αρχείο: **Linkwise Validated Sales**, με επιπλέον στήλη `Status`.
""")

# File upload
erp_file = st.file_uploader("📁 ERP Final Sales (.xlsx)", type="xlsx")
linkwise_file = st.file_uploader("📁 Linkwise Pending Sales (.xlsx)", type="xlsx")

if erp_file and linkwise_file:
    erp_df = pd.read_excel(erp_file)
    linkwise_df = pd.read_excel(linkwise_file)

    # Fill down to normalize ERP data
    erp_df[['Shopify Order Id', 'Customer', 'Handling Status', 'Status']] = erp_df[
        ['Shopify Order Id', 'Customer', 'Handling Status', 'Status']
    ].fillna(method='ffill')

    # Remove courier rows
    erp_df = erp_df[~erp_df['Order Lines/Product/Name'].str.lower().str.contains("courier", na=False)]

    # Define function to extract state_friendly from JSON
    def extract_state_friendly(json_str):
        try:
            # Handle double-encoded JSON
            if isinstance(json_str, str) and json_str.startswith('"{'):
                json_str = json.loads(json_str)  # decode outer layer
            data = json.loads(json_str)
            vouchers = data.get("courier_vouchers", [])
            for v in vouchers:  # πάρτο πρώτο valid state_friendly
                state = v.get("state_friendly", "").strip()
                if state:
                    return state
            return None
        except:
            return None

    # Create courier status map per order (από την πρώτη γραμμή με valid JSON)
    courier_status_by_order = (
        erp_df.dropna(subset=['Courier State'])
              .groupby('Shopify Order Id')['Courier State']
              .first()
              .apply(extract_state_friendly)
    )

    # Map σε όλες τις γραμμές
    erp_df['Courier Final Status'] = erp_df['Shopify Order Id'].map(courier_status_by_order)

    # Calculate order values
    def calculate_real_value(order_df):
        def calculate_line(row):
            if row['Order Lines/Invoiced Quantity'] == row['Order Lines/Delivery Quantity']:
                return row['Order Lines/Untaxed Invoiced Amount']
            else:
                return row['Order Lines/Untaxed Invoiced Amount'] * row['Order Lines/Delivery Quantity']
        return order_df.apply(calculate_line, axis=1).sum()

    # Mapping from ERP
    grouped_erp = dict(tuple(erp_df.groupby('Shopify Order Id')))

    # Process Linkwise entries
    statuses = []

    for idx, row in linkwise_df.iterrows():
        shopify_id = row['Advertiser Id']
        amount_linkwise = row['Amount']
        erp_rows = grouped_erp.get(shopify_id)

        if erp_rows is None:
            continue  # Αγνοείται αν δεν βρεθεί αντιστοιχία

        # Πρώτη γραμμή ERP για τη συγκεκριμένη παραγγελία
        first = erp_rows.iloc[0]
        customer = str(first['Customer']).lower()
        handling_status = str(first['Handling Status']).lower()
        order_status = str(first['Status']).lower()
        courier_status = str(first['Courier Final Status']).lower() if first['Courier Final Status'] else ''

        # Ακυρώσεις με βάση status
        if order_status in ['cancelled', 'lost', 'undelivered']:
            statuses.append("Cancel")
            continue
        if handling_status in ['cancelled', 'lost', 'not delivered']:
            statuses.append("Cancel")
            continue
        if any(name in customer for name in ['kalikatzarakis', 'καλικατζαράκης', 'ζευγούλη', 'zevgouli']):
            statuses.append("Cancel")
            continue
        if handling_status == 'checked' and order_status in ['cancelled', 'canceled', 'undelivered']:
            statuses.append("Pending")
            continue

        # Έλεγχος courier state
        if courier_status == 'delivered':
            total_delivery_qty = erp_rows['Order Lines/Delivery Quantity'].sum()
            if total_delivery_qty > 0:
                value_erp = calculate_real_value(erp_rows)
                if value_erp == 0:
                    statuses.append("Cancel")
                elif abs(value_erp - amount_linkwise) > 0.50:
                    statuses.append(f"Valid - η σωστή τιμή είναι {value_erp:.2f}€")
                else:
                    statuses.append("Valid")
            else:
                statuses.append("Cancel")
        elif courier_status in ['lost', 'canceled', 'returned to shipper']:
            statuses.append("Cancel")
        else:
            statuses.append("Pending")

    # Ενημέρωση Linkwise DataFrame με νέο Status
    valid_df = linkwise_df.copy()
    valid_df = valid_df.iloc[:len(statuses)]
    valid_df['Status'] = statuses

    # Export to Excel in memory
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        valid_df.to_excel(writer, index=False, sheet_name='Validated Sales')
    output.seek(0)

    st.success("✅ Το απαντητικό αρχείο δημιουργήθηκε επιτυχώς!")
    st.download_button(
        label="📥 Κατέβασε το Linkwise Validated Sales",
        data=output,
        file_name="Linkwise Validated Sales.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
