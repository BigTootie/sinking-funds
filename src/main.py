import flet as ft
import flet_charts as fch

from datetime import datetime
import json
import os

FILENAME = "funds.json"

def main(page: ft.Page):
    page.title = "Sinking Funds Dashboard"
    page.scroll = "auto"

    # --- Load funds ---
    if os.path.exists(FILENAME):
        with open(FILENAME, "r") as f:
            raw_funds = json.load(f)
            funds = [
                {
                    "name": x["name"],
                    "target": x["target"],
                    "frequency": x["frequency"],
                    "monthly": x["monthly"],
                    "balance": x["balance"],
                    "due_date": datetime.fromisoformat(x["due_date"]).date()
                } for x in raw_funds
            ]
    else:
        funds = []

    # --- UI controls ---
    funds_column = ft.Column()
    total_text = ft.Text(value="Total Monthly: $0.00", size=16, weight="bold")
    current_edit_fund = {"fund": None}

    # Pie chart
    funds_chart = fch.PieChart(
        expand=True,
        sections_space=0,
        center_space_radius=40,
        #width=400,
        #height=300,
        sections=[]
    )

    # Modal fields
    modal_name = ft.TextField(label="Name")
    modal_target = ft.TextField(label="Target", keyboard_type=ft.KeyboardType.NUMBER)
    modal_frequency = ft.TextField(label="Frequency", keyboard_type=ft.KeyboardType.NUMBER)
    modal_balance = ft.TextField(label="Balance", keyboard_type=ft.KeyboardType.NUMBER)
    modal_due_date = ft.DatePicker(value=datetime.now().date())

    # Modal dialog
    edit_dialog = ft.AlertDialog(
        modal=True,
        title=ft.Text("Edit Fund"),
        content=ft.Column([modal_name, modal_target, modal_frequency, modal_balance, modal_due_date], spacing=10),
        actions=[],
        actions_alignment=ft.MainAxisAlignment.END
    )

    # Save and Cancel actions
    def save_modal(e):
        fund = current_edit_fund["fund"]
        fund["name"] = modal_name.value
        fund["target"] = float(modal_target.value)
        fund["frequency"] = float(modal_frequency.value)
        fund["monthly"] = fund["target"] / fund["frequency"] if fund["frequency"] > 0 else 0
        fund["balance"] = float(modal_balance.value)
        fund["due_date"] = modal_due_date.value
        page.pop_dialog()
        refresh_funds()

    def cancel_modal(e):
        page.pop_dialog()

    edit_dialog.actions = [
        ft.ElevatedButton("Save", on_click=save_modal),
        ft.ElevatedButton("Cancel", on_click=cancel_modal)
    ]

    def open_edit_dialog(fund):
        current_edit_fund["fund"] = fund
        modal_name.value = fund["name"]
        modal_target.value = str(fund["target"])
        modal_frequency.value = str(fund["frequency"])
        modal_balance.value = str(fund["balance"])
        modal_due_date.value = fund["due_date"]
        page.show_dialog(edit_dialog)

    # Save funds to disk
    def save_funds():
        with open(FILENAME, "w") as f:
            json.dump([
                {
                    "name": x["name"],
                    "target": x["target"],
                    "frequency": x["frequency"],
                    "monthly": x["monthly"],
                    "balance": x["balance"],
                    "due_date": x["due_date"].isoformat()
                } for x in funds
            ], f, indent=2)

    # --- Refresh UI ---
    def refresh_funds():
        # 3 columns
        col1 = ft.Column(spacing=10)
        col2 = ft.Column(spacing=10)
        col3 = ft.Column(spacing=10)
        all_columns = [col1, col2, col3]
        funds_column.controls.clear()

        for i, fund in enumerate(funds):
            progress = min(fund["balance"] / fund["target"], 1.0) if fund["target"] > 0 else 0
            custom_input = ft.TextField(hint_text="Enter amount", width=100, keyboard_type=ft.KeyboardType.NUMBER)

            def add_amount(e, fund=fund, inp=custom_input):
                try:
                    val = float(inp.value)
                    fund["balance"] += val
                    inp.value = ""
                    refresh_funds()
                except:
                    pass

            def remove_amount(e, fund=fund, inp=custom_input):
                try:
                    val = float(inp.value)
                    fund["balance"] = max(0, fund["balance"] - val)
                    inp.value = ""
                    refresh_funds()
                except:
                    pass

            def delete_fund(e, fund=fund):
                funds.remove(fund)
                refresh_funds()

            card = ft.Card(
                content=ft.Column([
                    ft.Text(fund["name"], weight="bold", size=16),
                    ft.Text(f"Target: ${fund['target']:.2f}"),
                    ft.Text(f"Monthly: ${fund['monthly']:.2f}"),
                    ft.Text(f"Saved: ${fund['balance']:.2f}"),
                    ft.Text(f"Next Due: {fund['due_date'].strftime('%m/%d/%Y')}"),
                    ft.ProgressBar(value=progress, width=200, color="#4CAF50"),
                    ft.Row([
                        custom_input,
                        ft.ElevatedButton("Add", on_click=add_amount),
                        ft.ElevatedButton("Remove", bgcolor="#F44336", on_click=remove_amount),
                        ft.ElevatedButton("Edit", on_click=lambda e, f=fund: open_edit_dialog(f)),
                        ft.ElevatedButton("Delete", bgcolor="#F44336", on_click=delete_fund)
                    ], spacing=5)
                ], spacing=5),
                elevation=2,
                margin=5
            )

            # distribute cards to columns
            all_columns[i % 3].controls.append(card)

        funds_row = ft.Row([col1, col2, col3], spacing=20, alignment=ft.MainAxisAlignment.START)
        funds_column.controls.append(funds_row)

        # Update pie chart
        chart_data = [fch.PieChartSection(title=f["name"], value=f["target"]) for f in funds]
        funds_chart.sections = chart_data

        # Update total
        total = sum(f["monthly"] for f in funds)
        total_text.value = f"Total Monthly: ${total:.2f}"

        page.update()
        save_funds()

    # --- Add new fund UI ---
    name_input = ft.TextField(label="Fund Name")
    amount_input = ft.TextField(label="Target Amount", keyboard_type=ft.KeyboardType.NUMBER)
    frequency_input = ft.TextField(label="Frequency (months)", keyboard_type=ft.KeyboardType.NUMBER)
    due_date_input = ft.DatePicker(value=datetime.now().date())

    def add_fund(e):
        try:
            target = float(amount_input.value)
            freq = float(frequency_input.value)
            if freq <= 0:
                raise ValueError()
        except:
            page.snack_bar = ft.SnackBar(ft.Text("Invalid amount or frequency"))
            page.snack_bar.open = True
            page.update()
            return

        monthly = target / freq
        fund = {
            "name": name_input.value,
            "target": target,
            "frequency": freq,
            "monthly": monthly,
            "balance": 0.0,
            "due_date": due_date_input.value
        }
        funds.append(fund)
        name_input.value = ""
        amount_input.value = ""
        frequency_input.value = ""
        due_date_input.value = datetime.now().date()
        refresh_funds()

    # --- Layout ---
    page.add(ft.Column([
        ft.Text("Sinking Funds Dashboard", size=24, weight="bold"),
        funds_chart,
        name_input,
        amount_input,
        frequency_input,
        ft.Column([ft.Text("Next Due Date"), due_date_input]),
        ft.ElevatedButton("Add Fund", on_click=add_fund),
        ft.Divider(height=20),
        funds_column,
        total_text
    ], spacing=10))

    refresh_funds()


ft.app(target=main)