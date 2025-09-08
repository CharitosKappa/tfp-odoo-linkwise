import pandas as pd
import numpy as np

def process_linkwise_vs_erp(linkwise_df, erp_df):
    # Βήμα 1 - Fill-down
    fill_cols = ["Shopify Order Id", "Customer", "Handling Status", "Status"]
    erp_df[fill_cols] = erp_df[fill_cols].ffill()

    # Βήμα 2 - Αντιστοίχιση Linkwise με ERP μέσω Order Id
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
        handling_status = str(row["Handling Status"]).lower()
        order_status = str(row["Status_erp"]).lower()
        customer = str(row["Customer"])

        if order_status in {"canceled", "cancelled", "undelivered", "undeliverd"}:
            statuses.append("cancel")
        elif handling_status in {"canceled", "cancelled"}:
            statuses.append("cancel")
        elif customer.strip().lower() == "kalikatzarakis":
            statuses.append("cancel")
        elif handling_status == "checked" and order_status not in {"canceled", "cancelled", "undelivered", "undeliverd"}:
            statuses.append("pending")
        else:
            order_id = row["Shopify Order Id"]
            erp_lines = erp_df[erp_df["Shopify Order Id"] == order_id]
            erp_lines = erp_lines[~erp_lines["Order Lines/Product/Name"].str.contains("Courier", case=False, na=False)]

            line_values = []
            for _, line in erp_lines.iterrows():
                qty = line["Order Lines/Product/Quantity"]
                delivered = line["Order Lines/Product/Delivered"]
                unit_price = line["Order Lines/Product/Price Unit"]
                untaxed_amount = line["Order Lines/Product/Untaxed Invoiced Amount"]

                if qty == delivered:
                    value = untaxed_amount
                else:
                    value = unit_price * delivered
                line_values.append(value)

            erp_total = sum(line_values)
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
