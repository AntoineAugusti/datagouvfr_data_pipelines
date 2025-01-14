import pandas as pd
import requests

from datagouvfr_data_pipelines.config import (
    AIRFLOW_DAG_TMP,
    MINIO_URL,
    MINIO_BUCKET_DATA_PIPELINE_OPEN,
    SECRET_MINIO_DATA_PIPELINE_USER,
    SECRET_MINIO_DATA_PIPELINE_PASSWORD,
)
from datagouvfr_data_pipelines.utils.minio import send_files, compare_files
from datagouvfr_data_pipelines.utils.mattermost import send_message


def flatten_object(obj, prop):
    #obj = ast.literal_eval(x)
    res = ""
    for item in obj:
        res += f",{item[prop]}"
    return res[1:]


def process_agence_bio(ti):
    url = (
        "https://opendata.agencebio.org/api/gouv/operateurs/?departements="
        "01,02,03,04,05,06,07,08,09,10,11,12,13,14,15,16,17,18,19,21,22,23,"
        "24,25,26,27,28,29,2A,2B,30,31,32,33,34,35,36,37,38,39,40,41,42,43,"
        "44,45,46,47,48,49,50,51,52,53,54,55,56,57,58,59,60,61,62,63,64,65,"
        "66,67,68,69,70,71,72,73,74,75,76,77,78,79,80,81,82,83,84,85,86,87,"
        "88,89,90,91,92,93,94,95,971,972,973,974,976,977,978,984,986,987,"
        "988,989&nb=1000&debut="
    )
    cpt = 0
    res = []
    r = requests.get(f"{url}{str(cpt)}")
    data = r.json()
    res = data["items"]
    while data["items"]:
        print(cpt)
        cpt += 1000
        r = requests.get(f"{url}{str(cpt)}")
        data = r.json()
        res = res + data["items"]
    df_bio = pd.DataFrame(res)
    df_bio["flatten_activites"] = df_bio["activites"].apply(lambda x: flatten_object(x, "nom"))

    arr_cert = []
    arr_prod = []
    arr_adr = []
    for index, row in df_bio.iterrows():
        for cert in row["certificats"]:
            dict_cert = cert
            dict_cert["siret"] = row["siret"]
            dict_cert["id_bio"] = row["numeroBio"]
            arr_cert.append(dict_cert)
        for prod in row["productions"]:
            dict_prod = prod
            dict_prod["siret"] = row["siret"]
            dict_prod["id_bio"] = row["numeroBio"]
            arr_prod.append(dict_prod)
        for adr in row["adressesOperateurs"]:
            dict_adr = adr
            dict_adr["siret"] = row["siret"]
            dict_adr["id_bio"] = row["numeroBio"]
            arr_adr.append(dict_adr)

    df_cert = pd.DataFrame(arr_cert)
    df_prod = pd.DataFrame(arr_prod)
    df_adr = pd.DataFrame(arr_adr)

    df_cert = df_cert[
        [
            "id_bio",
            "siret",
            "organisme",
            "etatCertification",
            "dateSuspension",
            "dateArret",
            "dateEngagement",
            "dateNotification",
            "url", 
        ]
    ]
    df_cert = df_cert.rename(columns={
        "etatCertification": "etat_certification",
        "dateSuspension": "date_suspension",
        "dateArret": "date_arret",
        "dateEngagement": "date_engagement",
        "dateNotification": "date_notification"
    })

    df_prod["flatten_etatProductions"] = df_prod["etatProductions"].apply(lambda x: flatten_object(x, "etatProduction"))
    df_prod = df_prod[
        [
            "id_bio",
            "siret",
            "code",
            "nom",
            "flatten_etatProductions"
        ]
    ]
    df_prod = df_prod.rename(columns={"flatten_etatProductions": "etat_productions"})

    df_adr = df_adr[
        [
            "id_bio",
            "siret",
            "lieu",
            "codePostal",
            "ville",
            "lat",
            "long",
            "codeCommune",
            "active",
            "departementId",
            "typeAdresseOperateurs",
        ]
    ]
    df_adr = df_adr.rename(columns={
        "lieu": "adresse",
        "codePostal": "code_postal",
        "ville": "commune",
        "codeCommune": "code_commune",
        "departementId": "code_departement",
        "typeAdresseOperateurs": "type_adresse_operateurs"
    })

    df_bio = df_bio.drop(columns=["adressesOperateurs", "productions", "activites", "certificats"])
    df_bio = df_bio.rename(columns={
        "numeroBio": "id_bio",
        "raisonSociale": "nom_raison_sociale",
        "denominationcourante": "denomination_courante",
        "codeNAF": "code_naf",
        "dateMaj": "date_maj",
        "telephoneCommerciale": "telephone_commerciale",
        "siteWebs": "site_webs",
        "flatten_activites": "activites"
    })
    df_bio = df_bio[
        [
            "id_bio",
            "siret",
            "nom_raison_sociale",
            "denomination_courante",
            "telephone",
            "email",
            "code_naf",
            "gerant",
            "date_maj",
            "telephone_commerciale",
            "reseau",
            "categories",
            "site_webs",
            "mixite",
            "activites"
        ]
    ]

    df_bio.to_csv(f"{AIRFLOW_DAG_TMP}agence_bio/agence_bio_principal.csv", index=False)
    df_cert.to_csv(f"{AIRFLOW_DAG_TMP}agence_bio/agence_bio_certifications.csv", index=False)
    df_prod.to_csv(f"{AIRFLOW_DAG_TMP}agence_bio/agence_bio_productions.csv", index=False)
    df_adr.to_csv(f"{AIRFLOW_DAG_TMP}agence_bio/agence_bio_adresses.csv", index=False)

    ti.xcom_push(key="nb_id_bio", value=str(df_bio["id_bio"].nunique()))
    ti.xcom_push(key="nb_siret", value=str(df_bio["siret"].nunique()))


def send_file_to_minio():
    send_files(
        MINIO_URL=MINIO_URL,
        MINIO_BUCKET=MINIO_BUCKET_DATA_PIPELINE_OPEN,
        MINIO_USER=SECRET_MINIO_DATA_PIPELINE_USER,
        MINIO_PASSWORD=SECRET_MINIO_DATA_PIPELINE_PASSWORD,
        list_files=[
            {
                "source_path": f"{AIRFLOW_DAG_TMP}agence_bio/",
                "source_name": "agence_bio_principal.csv",
                "dest_path": "agence_bio/new/",
                "dest_name": "agence_bio_principal.csv",
            },
            {
                "source_path": f"{AIRFLOW_DAG_TMP}agence_bio/",
                "source_name": "agence_bio_certifications.csv",
                "dest_path": "agence_bio/new/",
                "dest_name": "agence_bio_certifications.csv",
            },
            {
                "source_path": f"{AIRFLOW_DAG_TMP}agence_bio/",
                "source_name": "agence_bio_productions.csv",
                "dest_path": "agence_bio/new/",
                "dest_name": "agence_bio_productions.csv",
            },
            {
                "source_path": f"{AIRFLOW_DAG_TMP}agence_bio/",
                "source_name": "agence_bio_adresses.csv",
                "dest_path": "agence_bio/new/",
                "dest_name": "agence_bio_adresses.csv",
            }
        ],
    )


def compare_files_minio():
    is_same = compare_files(
        MINIO_URL=MINIO_URL,
        MINIO_BUCKET=MINIO_BUCKET_DATA_PIPELINE_OPEN,
        MINIO_USER=SECRET_MINIO_DATA_PIPELINE_USER,
        MINIO_PASSWORD=SECRET_MINIO_DATA_PIPELINE_PASSWORD,
        file_path_1="agence_bio/new/",
        file_name_2="agence_bio_principal.csv",
        file_path_2="agence_bio/latest/",
        file_name_1="agence_bio_principal.csv",
    )
    if is_same:
        return False

    if is_same is None:
        print("First time in this Minio env. Creating")

    send_files(
        MINIO_URL=MINIO_URL,
        MINIO_BUCKET=MINIO_BUCKET_DATA_PIPELINE_OPEN,
        MINIO_USER=SECRET_MINIO_DATA_PIPELINE_USER,
        MINIO_PASSWORD=SECRET_MINIO_DATA_PIPELINE_PASSWORD,
        list_files=[
            {
                "source_path": f"{AIRFLOW_DAG_TMP}agence_bio/",
                "source_name": "agence_bio_principal.csv",
                "dest_path": "agence_bio/latest/",
                "dest_name": "agence_bio_principal.csv",
            },
            {
                "source_path": f"{AIRFLOW_DAG_TMP}agence_bio/",
                "source_name": "agence_bio_certifications.csv",
                "dest_path": "agence_bio/latest/",
                "dest_name": "agence_bio_certifications.csv",
            },
            {
                "source_path": f"{AIRFLOW_DAG_TMP}agence_bio/",
                "source_name": "agence_bio_productions.csv",
                "dest_path": "agence_bio/latest/",
                "dest_name": "agence_bio_productions.csv",
            },
            {
                "source_path": f"{AIRFLOW_DAG_TMP}agence_bio/",
                "source_name": "agence_bio_adresses.csv",
                "dest_path": "agence_bio/latest/",
                "dest_name": "agence_bio_adresses.csv",
            }
        ],
    )

    return True


def send_notification(ti):
    nb_id_bio = ti.xcom_pull(key="nb_id_bio", task_ids="process_agence_bio")
    nb_siret = ti.xcom_pull(key="nb_siret", task_ids="process_agence_bio")
    send_message(
        text=(
            ":mega: Données Agence Bio (certificats professionnels Bio) mises à jour.\n"
            f"- {nb_id_bio} identifiants Bio référencés\n"
            f"- {nb_siret} établissements (siret) représentés\n"
            f"- Données stockées sur Minio - Bucket {MINIO_BUCKET_DATA_PIPELINE_OPEN}"
        )
    )
