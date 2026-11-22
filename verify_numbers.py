"""Independent check of the numbers the deployed agent reports."""
import pandas as pd

df = pd.read_csv("E:/work/mistral1/2/csv-analyst/sample/in_period_tracking.csv")
print("rows:", len(df), "cols:", len(df.columns))

print("sum Actual_Supplier_Payments_GBP:", round(df["Actual_Supplier_Payments_GBP"].sum(), 2),
      "| non-null:", int(df["Actual_Supplier_Payments_GBP"].notna().sum()))

m = df[df["Actual_CFD_Payments_GBP"] > 10_000_000]
print("days Actual_CFD > 10M:", len(m))
print("  sum Actual_CFD_Payments_GBP:", round(m["Actual_CFD_Payments_GBP"].sum(), 2))
print("  mean Actual_Eligible_Demand_MWh:", round(m["Actual_Eligible_Demand_MWh"].mean(), 4))
top = m.loc[m["Actual_CFD_Payments_GBP"].idxmax()]
print("  top day:", top["Settlement_Date"], "->", top["Actual_CFD_Payments_GBP"])

print("sum Actual_CFD_Payments_GBP (all non-null):", round(df["Actual_CFD_Payments_GBP"].sum(), 2),
      "| non-null:", int(df["Actual_CFD_Payments_GBP"].notna().sum()))
print("mean Actual_Eligible_Demand_MWh:", round(df["Actual_Eligible_Demand_MWh"].mean(), 4))
