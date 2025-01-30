import streamlit as st
import pandas as pd

###############################################################################
# 1) Paramètres de calcul et logique Supply Planning
###############################################################################
classification_service_levels = {
    'A': 0.99,
    'B': 0.95,
    'C': 0.90
}

z_values = {
    0.90: 1.28,
    0.95: 1.645,
    0.99: 2.33
}

def calculate_safety_stock(demand_std, service_level=0.95):
    Z = z_values.get(service_level, 1.645)
    return Z * demand_std

def calculate_demand_std(demand_series):
    return demand_series.std()

def supply_planning(demand_data: pd.DataFrame,
                    initial_stocks: dict,
                    selected_products: list) -> pd.DataFrame:
    """
    Calcule un plan d'appro mensuel (Articles x Month), incluant :
    - Stock de début
    - Demande
    - Stock de sécurité
    - Commande
    - Stock de fin
    """
    results = []

    # Mapping mois (fr -> int)
    month_mapping = {
        'janvier': 1, 'février': 2, 'mars': 3, 'avril': 4, 'mai': 5, 'juin': 6,
        'juillet': 7, 'août': 8, 'septembre': 9, 'octobre': 10, 'novembre': 11, 'décembre': 12
    }
    # On calcule un champ numérique "Month" pour trier
    demand_data['Month'] = demand_data['DateDuMois - Mois'].str.lower().map(month_mapping)

    # Filtrer sur les produits sélectionnés
    demand_data = demand_data[demand_data['Articles'].isin(selected_products)]

    for product in selected_products:
        product_data = demand_data[demand_data['Articles'] == product].copy()
        product_data.sort_values(by='Month', inplace=True)

        # Stock initial (défini par l'utilisateur)
        current_stock = initial_stocks.get(product, 0)

        if product_data.empty:
            continue

        # Classification & niveau de service
        classification = product_data['Classification_ABC'].iloc[0]
        service_level = classification_service_levels.get(classification, 0.95)

        # Écart-type de la demande (simple) sur toutes les lignes de ce produit
        demand_std = calculate_demand_std(product_data['UVC_2025'])

        for _, row in product_data.iterrows():
            demand = row['UVC_2025']
            month = row['Month']
            stock_safety = calculate_safety_stock(demand_std, service_level)

            stock_beginning = current_stock
            order_qty = max(0, (demand + stock_safety) - stock_beginning)
            stock_ending = stock_beginning + order_qty - demand

            results.append({
                'Articles': product,
                'Month': int(month) if pd.notna(month) else None,
                'Stock_Beginning': stock_beginning,
                'Demand': demand,
                'Safety_Stock': round(stock_safety, 2),
                'Order': round(order_qty, 2),
                'Stock_Ending': round(stock_ending, 2),
                'Classification_ABC': classification,
                'Service_Level': service_level
            })

            current_stock = stock_ending

    plan_df = pd.DataFrame(results)
    plan_df.sort_values(by=['Articles', 'Month'], inplace=True)
    return plan_df

###############################################################################
# 2) Helpers pour l'édition automatique (sans bouton)
###############################################################################
def sync_plan_changes_to_data(
    plan_edited: pd.DataFrame,
    plan_original: pd.DataFrame,
    demand_data: pd.DataFrame,
    initial_stocks: dict,
    month_col_name: str = "DateDuMois - Mois"
):
    """
    Compare le plan édité (plan_edited) avec le plan original (plan_original).
    - Si la colonne "Demand" a été changée, on répercute la modification dans demand_data['UVC_2025'].
    - Si la colonne "Stock_Beginning" a été changée, on répercute la modification dans le stock initial (si c'est le premier mois pour l'article).
    """
    if plan_edited.empty or plan_original.empty:
        return  # rien à faire

    # Mapping mois numérique -> nom texte minuscule
    inv_month_map = {
        1: 'janvier', 2: 'février', 3: 'mars', 4: 'avril', 5: 'mai', 6: 'juin',
        7: 'juillet', 8: 'août', 9: 'septembre', 10: 'octobre', 11: 'novembre', 12: 'décembre'
    }

    # On crée un index commun pour comparer plus facilement
    # (Articles, Month) doit être unique
    plan_edited = plan_edited.set_index(["Articles", "Month"])
    plan_original = plan_original.set_index(["Articles", "Month"])

    for idx, row_edited in plan_edited.iterrows():
        if idx not in plan_original.index:
            continue
        row_original = plan_original.loc[idx]

        # Comparer Demand
        if row_edited["Demand"] != row_original["Demand"]:
            # On a modifié la demande
            art, mo = idx  # idx = (article, month)
            new_demand = row_edited["Demand"]

            # On met à jour demand_data
            month_name = inv_month_map.get(mo, None)
            if month_name:
                mask = (
                    (demand_data["Articles"] == art)
                    & (demand_data[month_col_name].str.lower() == month_name)
                )
                demand_data.loc[mask, "UVC_2025"] = new_demand

        # Comparer Stock_Beginning
        if row_edited["Stock_Beginning"] != row_original["Stock_Beginning"]:
            # On a modifié le stock de début
            art, mo = idx
            new_begin = row_edited["Stock_Beginning"]

            # Pour savoir si c'est le premier mois de l'article => on regarde le min dans demand_data
            product_mask = (demand_data["Articles"] == art)
            # Convertit le mois texte en numérique pour trouver le min
            numeric_months = demand_data.loc[product_mask, month_col_name].str.lower().map({
                v: k for k, v in inv_month_map.items()
            })
            if mo == numeric_months.min():
                # => on met à jour le stock initial
                initial_stocks[art] = new_begin

    # On retire les index pour éviter de casser l'ordre d'origine
    plan_edited.reset_index(inplace=True)
    plan_original.reset_index(inplace=True)


###############################################################################
# 3) Application Streamlit principale (sans bouton de recalcul)
###############################################################################
def main():
    st.title("Supply Planning - Edition automatique (Demand & Stock)")

    # -- Chargement initial
    uploaded_file = st.file_uploader("Charger un fichier Excel (Articles, DateDuMois - Mois, UVC_2025, Classification_ABC)", type=["xlsx"])
    if not uploaded_file:
        st.info("Veuillez charger un fichier Excel pour commencer.")
        return

    # Lecture du fichier
    df_raw = pd.read_excel(uploaded_file)

    # Vérification des colonnes
    required_cols = ["Articles", "DateDuMois - Mois", "UVC_2025", "Classification_ABC"]
    if not all(c in df_raw.columns for c in required_cols):
        st.error("Colonnes requises manquantes : Articles, DateDuMois - Mois, UVC_2025, Classification_ABC.")
        return

    # -- Stockage / initialisation en session_state si non présent
    if "demand_data" not in st.session_state:
        st.session_state["demand_data"] = df_raw.copy()

    if "selected_products" not in st.session_state:
        st.session_state["selected_products"] = df_raw["Articles"].unique().tolist()

    if "initial_stocks" not in st.session_state:
        # Initialiser à 0 pour chaque produit
        stock_dict = {}
        for prod in df_raw["Articles"].unique():
            stock_dict[prod] = 0
        st.session_state["initial_stocks"] = stock_dict

    if "plan" not in st.session_state:
        st.session_state["plan"] = pd.DataFrame()

    # -- 1) Édition de la demande via st_data_editor
    st.subheader("1) Éditer la demande (UVC_2025, Classification, etc.)")
    demand_data_edited = st_data_editor(
        st.session_state["demand_data"],
        key="demand_data_editor"
    )
    # On met à jour la demande stockée
    st.session_state["demand_data"] = demand_data_edited

    # -- 2) Sélection des produits
    st.subheader("2) Sélection des produits")
    all_products = sorted(demand_data_edited["Articles"].unique().tolist())
    selected_products = st.multiselect(
        "Produits à planifier",
        options=all_products,
        default=all_products
    )
    st.session_state["selected_products"] = selected_products

    # -- 3) Saisie des stocks initiaux
    st.subheader("3) Saisir les stocks initiaux")
    for prod in selected_products:
        st.session_state["initial_stocks"][prod] = st.number_input(
            f"Stock initial pour {prod}",
            min_value=0,
            step=1,
            value=st.session_state["initial_stocks"][prod]
        )

    # -- 4) Calcul du plan automatiquement
    plan_computed = supply_planning(
        st.session_state["demand_data"].copy(),
        st.session_state["initial_stocks"].copy(),
        st.session_state["selected_products"]
    )

    # -- 5) Édition du plan (pour éventuellement changer "Demand" ou "Stock_Beginning")
    st.subheader("4) Éditer le plan (Demand / Stock_Beginning) et recalcul automatique")
    plan_original = plan_computed.copy()  # on garde une copie pour comparer
    plan_edited = st_data_editor(
        plan_computed,
        key="plan_data_editor"
    )

    # -- 6) Synchroniser changements du plan dans la demande ou le stock
    #       (si "Demand" ou "Stock_Beginning" ont changé)
    sync_plan_changes_to_data(
        plan_edited=plan_edited,
        plan_original=plan_original,
        demand_data=st.session_state["demand_data"],
        initial_stocks=st.session_state["initial_stocks"]
    )

    # -- 7) Met à jour st.session_state["plan"] après synchro
    #       (le plan sera recalculé automatiquement au prochain run)
    st.session_state["plan"] = plan_edited

    # Affichage final
    st.write("### Plan d'appro final (après modifications)")
    st.dataframe(plan_edited)

    # -- 8) Téléchargement CSV
    st.write("### Télécharger en CSV UTF-8")
    csv_data = plan_edited.to_csv(index=False).encode("utf-8")
    st.download_button(
        label="Télécharger CSV (UTF-8)",
        data=csv_data,
        file_name="supply_plan.csv",
        mime="text/csv"
    )

if __name__ == "__main__":
    main()
