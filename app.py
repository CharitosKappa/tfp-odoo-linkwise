import io
import numpy as np
import pandas as pd
import streamlit as st
import streamlit_authenticator as stauth
from collections.abc import Mapping

# ------------------------------------------------------
# Page config (πρέπει να είναι η 1η Streamlit κλήση)
# ------------------------------------------------------
st.set_page_config(page_title="Linkwise ← ERP Status", page_icon="✅", layout="centered")

# ------------------------------------------------------
# Helpers
# ------------------------------------------------------
def to_dict(obj):
    """Μετατρέπει οποιοδήποτε Mapping (π.χ. st.secrets) σε κανονικό, mutable dict (deep)."""
    if isinstance(obj, Mapping):
        return {k: to_dict(v) for k, v in obj.items()}
    return obj

def process_files(erp_df: pd.DataFrame, lw_df: pd.DataFrame) -> pd.DataFrame:
    # 1) Fill-down στο ERP
    cols_to_ffill = ["Shopify Order Id", "Customer", "Handling Status", "Status"]
    for c in cols_to_ffill:
        if c not in erp_df.columns:
            raise ValueError(f"Λείπει στήλη από ERP: {c}")
    erp_df[cols_to_ffill] = erp_df[cols_to_ffill].ffill()

    # 2) Matching: Shopify Order Id (ERP) == Advertiser Id (Linkwise)
    if "Advertiser Id" not in lw_df.columns or "Amount" not in lw_df.columns:
        raise ValueError("Στο Linkwise λείπουν οι στήλες 'Advertiser Id' ή/και 'Amount'.")
    erp_df["ShopifyOrderId_norm"] = pd.to_numeric(erp_df["Shopify Order Id"], errors="coerce")
    lw_df["__AdvertiserId_norm"] = pd.to_numeric(lw_df["Advertiser Id"], errors="coerce")
    erp_grouped = erp_df.groupby("ShopifyOrderId_norm", dropna=True)

    # Απαραίτητες στήλες ERP για ποσά/ποσότητες
    req_cols = [
        "Order Lines/Product/Name",
        "Order Lines/Untaxed Invoiced Amount",
        "Order Lines/Delivery Quantity",
    ]
    for c in req_cols:
        if c not in erp_df.columns:
            raise ValueError(f"Λείπει στήλη από ERP: {c}")

    has_qty = "Order Lines/Quantity" in erp_df.columns

    def status_for_row(advertiser_id: float, lw_amount: float) -> str | None:
        if pd.isna(advertiser_id) or advertiser_id not in erp_grouped.groups:
            # καμία αντιστοίχιση → αφήνουμε κενό Status (δεν διαγράφουμε τη γραμμή)
            return None

        erp_order = erp_grouped.get_group(advertiser_id)

        # 3) Κανόνες κατάστασης (σειρά προτεραιότητας)
        s_any_cancel = erp_order["Status"].astype(str).str.lower().isin(
            ["canceled", "cancelled", "undelivered", "undeliverd"]
        ).any()
        if s_any_cancel:
            return "cancel"

        hs_any_cancel = erp_order["Handling Status"].astype(str).str.lower().isin(
            ["canceled", "cancelled"]
        ).any()
        if hs_any_cancel:
            return "cancel"

        cust_cancel = (erp_order["Customer"].astype(str).str.lower() == "kalikatzarakis").any()
        if cust_cancel:
            return "cancel"

        checked = (erp_order["Handling Status"].astype(str).str.lower() == "checked").any()
        if checked and not s_any_cancel:
            return "pending"

        # 4) Έλεγχος Ποσών (αγνοώντας "Courier")
        no_courier = erp_order[
            ~erp_order["Order Lines/Product/Name"].astype(str).str.contains("Courier", case=False, na=False)
        ].copy()

        if has_qty:
            qty = pd.to_numeric(no_courier["Order Lines/Quantity"], errors="coerce").fillna(0.0)
        else:
            qty = pd.to_numeric(no_courier["Order Lines/Delivery Quantity"], errors="coerce").fillna(0.0)

        delivered = pd.to_numeric(no_courier["Order Lines/Delivery Quantity"], errors="coerce").fillna(0.0)
        untaxed = pd.to_numeric(no_courier["Order Lines/Untaxed Invoiced Amount"], errors="coerce").fillna(0.0)

        # ΝΕΑ ΛΟΓΙΚΗ line_value:
        # 1) Αν Quantity == Delivered → line_value = Untaxed Invoiced Amount (line total από ERP)
        # 2) Αν Quantity > Delivered → Unit Price = Untaxed/Quantity; line_value = Unit Price * Delivered
        line_vals = []
        for q, d, u in zip(qty, delivered, untaxed):
            if q == d:
                line_vals.append(u)
            elif q > d:
                unit_price = (u / q) if q != 0 else 0.0
                line_vals.append(unit_price * d)
            else:
                # q < d → διατηρούμε u (όπως έρχεται από ERP)
                line_vals.append(u)

        erp_total = float(np.nansum(line_vals))

        # Κανόνες σύγκρισης (τελικό prompt):
        # ERP_Total = 0 → cancel
        if abs(erp_total) < 0.01:
            return "cancel"
        # |ERP_Total − Amount| ≈ Amount (±0,01€) → cancel  (δηλ. abs((ERP-Amount) - Amount) <= 0.01)
        if abs((erp_total - lw_amount) - lw_amount) <= 0.01:
            return "cancel"
        # |ERP_Total − Amount| ≤ 0,01 → valid
        if abs(erp_total - lw_amount) <= 0.01:
            return "valid"
        # Σχετική διαφορά ≤ 1% → valid
        rel_diff = (abs(erp_total - lw_amount) / abs(lw_amount)) if lw_amount != 0 else np.inf
        if rel_diff <= 0.01:
            return "valid"
        # Αλλιώς → valid - η σωστή τιμή είναι [ERP_Total]
        return f"valid - η σωστή τιμή είναι {erp_total:.2f}"

    statuses = [status_for_row(r["__AdvertiserId_norm"], r["Amount"]) for _, r in lw_df.iterrows()]

    out = lw_df.copy()
    out["Status"] = statuses

    # Καθαρισμός βοηθητικών
    if "__AdvertiserId_norm" in out.columns:
        out = out.drop(columns=["__AdvertiserId_norm"], errors="ignore")

    # Αποφυγή τυχόν διπλών στηλών
    dedup = [c for i, c in enumerate(out.columns) if c not in out.columns[:i]]
    out = out[dedup]
    return out

# ------------------------------------------------------
# Auth (με deep-copy των secrets για αποφυγή TypeError)
# ------------------------------------------------------
# try:
#     cfg = to_dict(st.secrets)  # st.secrets -> mutable dict
#     credentials_cfg = cfg["credentials"]
#     cookie_cfg = cfg["cookie"]
# except Exception as e:
#     st.error(
#         "❌ Δεν βρέθηκαν/δεν διαβάστηκαν σωστά τα Secrets.\n\n"
#         "Βεβαιώσου ότι υπάρχει το `.streamlit/secrets.toml` με αυτό το σχήμα:\n\n"
#         "[credentials]\n"
#         "  [credentials.usernames.alice]\n"
#         '  name = "Alice"\n'
#         '  email = "alice@example.com"\n'
#         '  password = "$2b$12$...hash..."\n\n'
#         "[cookie]\n"
#         'name = "order-validator-auth"\n'
#         'key = "τυχαίο_μακρύ_μυστικό"\n'
#         "expiry_days = 30\n"
#     )
#     st.stop()

# authenticator = stauth.Authenticate(
#     credentials_cfg,                 # mutable dict πλέον
#     cookie_cfg["name"],
#     cookie_cfg["key"],
#     cookie_cfg.get("expiry_days", 30),
# )

# authenticator.login("main")

# if st.session_state.get("authentication_status") is True:
#     authenticator.logout("Logout", "sidebar")
#     st.sidebar.success(f"Logged in: {st.session_state.get('name', '')}")
# elif st.session_state.get("authentication_status") is False:
#     st.error("❌ Λάθος username ή password.")
#     st.stop()
# else:
#     st.info("🔐 Παρακαλώ κάνε login.")
#     st.stop()


# ------------------------------------------------------
# APP UI
# ------------------------------------------------------
st.title("Linkwise (Pending Sales) — Status από ERP")
st.markdown("Ανέβασε τα 2 αρχεία Excel και πάτα **Process** για να κατεβάσεις το αποτέλεσμα.")

erp_file = st.file_uploader("Εδώ ανεβάζεις το report από το Odoo", type=["xlsx"])
linkwise_file = st.file_uploader("Εδώ ανεβάζεις το αρχείο από την Linkwise", type=["xlsx"])

if st.button("Process", type="primary", disabled=not (erp_file and linkwise_file)):
    try:
        erp_df = pd.read_excel(erp_file)
        lw_df = pd.read_excel(linkwise_file)
        result_df = process_files(erp_df, lw_df)

        # Δημιουργία Excel σε μνήμη
        bio = io.BytesIO()
        with pd.ExcelWriter(bio, engine="xlsxwriter") as writer:
            result_df.to_excel(writer, index=False, sheet_name="Linkwise+Status")
        bio.seek(0)

        st.success("Ολοκληρώθηκε! Κατέβασε το αρχείο παρακάτω.")
        st.download_button(
            label="⬇️ Download: Linkwise (Pending Sales) - with Status.xlsx",
            data=bio,
            file_name="Linkwise (Pending Sales) - with Status.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

        st.subheader("Preview")
        st.dataframe(result_df.head(20))
    except Exception as e:

        st.error(f"Σφάλμα: {e}")
