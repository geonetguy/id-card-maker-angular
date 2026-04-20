from types import SimpleNamespace
from pathlib import Path
import toga
from toga.style import Pack
from toga.style.pack import COLUMN, ROW
from ..core.csv_utils import EXPECTED_COLUMNS

def build_ui(app: toga.App) -> SimpleNamespace:
    # Stripe
    stripe_path = Path(__file__).resolve().parent.parent / "resources" / "stripe.png"
    stripe_image = toga.Image(str(stripe_path))
    stripe_view  = toga.ImageView(stripe_image, style=Pack(height=20, margin_bottom=6))
    stripe_row   = toga.Box(children=[stripe_view], style=Pack(direction=ROW))

    # Inputs
    name_input  = toga.TextInput(placeholder="Full Name",   style=Pack(width=300))
    id_input    = toga.TextInput(placeholder="ID Number",   style=Pack(width=300))
    date_input  = toga.TextInput(placeholder="YYYY-MM-DD",  style=Pack(width=300))
    email_input = toga.TextInput(placeholder="Email",       style=Pack(width=300))

    # Top action buttons
    pick_template_btn  = toga.Button("Choose Template…",  style=Pack(margin_right=8))
    pick_signature_btn = toga.Button("Choose Signature…", style=Pack(margin_right=8))
    load_csv_btn       = toga.Button("Load CSV…",         style=Pack(margin_right=8))
    generate_all_btn   = toga.Button("Generate All Cards",style=Pack(margin_right=8))
    save_table_btn     = toga.Button("Save Table",        style=Pack(margin_right=8))
    email_selected_btn = toga.Button("Email Selected", style=Pack(margin_right=8))
    email_all_btn      = toga.Button("Email All",         style=Pack(margin_right=8))
    clear_cards_btn    = toga.Button("Clear cards",       style=Pack(margin_right=8))

    # Add/Update + New
    add_member_btn = toga.Button("Add Member", style=Pack(margin_right=8))
    new_member_btn = toga.Button("New Member")  # <<— lets you return to Add mode any time

    status_label = toga.Label("Pick a template to begin.",style=Pack(font_size=14, font_weight="bold", padding_top=4, padding_bottom=4) )
    progress     = toga.ProgressBar(max=100, value=0, style=Pack(margin_top=8))

    # Table
    csv_table = toga.Table(
        headings=EXPECTED_COLUMNS,
        data=[],
        style=Pack(flex=1, margin_top=8, height=240),
        multiple_select=False,
    )

    # Preview — image set later
    preview_imageview = toga.ImageView(style=Pack(width=520, height=340))
    state = SimpleNamespace(template_path=None)

    # Rows/columns
    row_files = toga.Box(
        children=[
            pick_template_btn, pick_signature_btn, load_csv_btn,
            generate_all_btn, save_table_btn, clear_cards_btn,email_selected_btn, email_all_btn
        ],
        style=Pack(direction=ROW, margin_bottom=8),
    )

    row_name  = toga.Box(children=[toga.Label("Name",      style=Pack(width=110)), name_input],  style=Pack(direction=ROW, margin_bottom=6))
    row_id    = toga.Box(children=[toga.Label("ID Number", style=Pack(width=110)), id_input],    style=Pack(direction=ROW, margin_bottom=6))
    row_date  = toga.Box(children=[toga.Label("Date",      style=Pack(width=110)), date_input],  style=Pack(direction=ROW, margin_bottom=6))
    row_email = toga.Box(children=[toga.Label("Email",     style=Pack(width=110)), email_input], style=Pack(direction=ROW, margin_bottom=6))

    # Add + New on one row
    row_actions = toga.Box(
        children=[add_member_btn, new_member_btn],
        style=Pack(direction=ROW, margin_top=8, margin_bottom=8)
    )

    left_col  = toga.Box(children=[row_name, row_id, row_date, row_email, row_actions], style=Pack(direction=COLUMN, flex=1, margin_right=12))
    right_col = toga.Box(children=[preview_imageview], style=Pack(direction=COLUMN))
    main_row  = toga.Box(children=[left_col, right_col], style=Pack(direction=ROW, margin_bottom=8))

    root = toga.Box(children=[row_files, main_row, status_label, progress, csv_table], style=Pack(direction=COLUMN, margin=12))
    container = toga.Box(children=[toga.Box(children=[stripe_view], style=Pack(direction=ROW)), root], style=Pack(direction=COLUMN))

    return SimpleNamespace(
        container=container,
        root=root,
        stripe_view=stripe_view,
        # Inputs
        name_input=name_input, id_input=id_input, date_input=date_input, email_input=email_input,
        # Buttons
        pick_template_btn=pick_template_btn, 
        pick_signature_btn=pick_signature_btn, 
        load_csv_btn=load_csv_btn,
        generate_all_btn=generate_all_btn, 
        save_table_btn=save_table_btn, 
        clear_cards_btn=clear_cards_btn,
        add_member_btn=add_member_btn, 
        new_member_btn=new_member_btn,
        email_selected_btn=email_selected_btn, 
        email_all_btn=email_all_btn,
        # Status/Progress
        status_label=status_label, progress=progress,
        # Table + Preview + State
        csv_table=csv_table, preview_imageview=preview_imageview, state=state,
    )
