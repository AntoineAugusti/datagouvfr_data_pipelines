from airflow.models import DAG
from airflow.operators.python import PythonOperator
from airflow.utils.dates import days_ago
from datetime import timedelta, datetime
from difflib import SequenceMatcher
from datagouvfr_data_pipelines.config import (
    MATTERMOST_DATAGOUV_ACTIVITES,
    MATTERMOST_DATAGOUV_SCHEMA_ACTIVITE,
)
from datagouvfr_data_pipelines.utils.mattermost import send_message
from datagouvfr_data_pipelines.utils.datagouv import get_last_items
import requests

DAG_NAME = "dgv_notification_activite"

TIME_PERIOD = {"hours": 1}


def check_new(ti, **kwargs):
    templates_dict = kwargs.get("templates_dict")
    # we want everything that happened since this date
    start_date = datetime.now() - timedelta(**TIME_PERIOD)
    end_date = datetime.now()
    items = get_last_items(templates_dict["type"], start_date, end_date)
    # items = get_last_items(templates_dict['type'], start_date)
    ti.xcom_push(key="nb", value=str(len(items)))
    arr = []
    for item in items:
        mydict = {}
        if "name" in item:
            mydict["name"] = item["name"]
        if "title" in item:
            mydict["name"] = item["title"]
        if "page" in item:
            mydict["page"] = item["page"]
        arr.append(mydict)
    ti.xcom_push(key=templates_dict["type"], value=arr)


def similar(a, b):
    return SequenceMatcher(None, a, b).ratio()


def get_organization(data):
    orga = ""
    if data["organization"] is not None:
        if "name" in data["organization"]:
            orga = f"(Organisation {data['organization']['name']})"
    if data["owner"] is not None:
        if "first_name" in data["owner"]:
            orga = f"(Utilisateur {data['owner']['first_name']} {data['owner']['last_name']})"
    return orga


def schema_suspicion(catalog, resource, orga):
    schemas = [schema["title"] for schema in catalog]
    best_score = 0
    schema_title = ""
    for schema in schemas:
        score = similar(schema, resource["name"])
        if score > best_score:
            best_score = score
            schema_title = schema
    if best_score > 0.6:
        message = (
            ":mega: Nouveau jeu de donnée suspecté d'appartenir au schéma "
            f"**{schema_title}** {orga}: \n - [{resource['name']}]({resource['page']})"
        )
        send_message(message, MATTERMOST_DATAGOUV_SCHEMA_ACTIVITE)


def parse_schema_catalog(
    schema, resource, schema_name, publierDetection, schema_type, validata_url
):
    if schema["name"] == resource["schema"]["name"]:
        schema_name = schema["title"]
        publierDetection = False
        if "publish_source" in resource["extras"]:
            if resource["extras"]["publish_source"] == "publier.etalab.studio":
                publierDetection = True
        if schema["schema_type"] == "tableschema":
            schema_type = "tableschema"
            result2 = requests.get(
                "https://api.validata.etalab.studio/validate?schema="
                f"{schema['schema_url']}&url={resource['url']}"
            )
            try:
                res = result2.json()["report"]["valid"]
                validata_url = (
                    "https://validata.fr/table-schema?input=url&url="
                    f"{resource['url']}&schema_url={schema['schema_url']}"
                )
            except:
                res = False
        else:
            schema_type = "other"
    return schema_name, publierDetection, schema_type, res, validata_url


def parse_resource_if_schema(catalog, resource, item, orga, is_schema):
    if resource["schema"]:
        is_schema = True
        schema_name = None
        publierDetection = False
        schema_type = ""
        res = None
        validata_url = ""
        for s in catalog:
            (
                schema_name,
                publierDetection,
                schema_type,
                res,
                validata_url,
            ) = parse_schema_catalog(
                s,
                resource,
                schema_name,
                publierDetection,
                schema_type,
                res,
                validata_url,
            )
        if not schema_name:
            schema_name = resource["schema"]["name"]
        message = (
            ":mega: Nouvelle ressource déclarée appartenant au schéma "
            f"**{schema_name}** {orga}: \n - [Lien vers le jeu de donnée]({item['page']})"
        )
        if schema_type == "tableschema":
            if res:
                message += f"\n - [Ressource valide]({validata_url}) :partying_face:"
            else:
                message += f"\n - [Ressource non valide]({validata_url}) :weary:"
        if publierDetection:
            message += "\n - Made with publier.etalab.studio :doge-cool:"
        send_message(message, MATTERMOST_DATAGOUV_SCHEMA_ACTIVITE)
    return is_schema


def check_schema(ti):
    nb_datasets = float(ti.xcom_pull(key="nb", task_ids="check_new_datasets"))
    datasets = ti.xcom_pull(key="datasets", task_ids="check_new_datasets")
    r = requests.get("https://schema.data.gouv.fr/schemas/schemas.json")
    catalog = r.json()["schemas"]
    if nb_datasets > 0:
        for item in datasets:
            r = requests.get(
                item["page"].replace("data.gouv.fr/fr/", "data.gouv.fr/api/1/")
            )
            data = r.json()
            orga = get_organization(data)
            try:
                is_schema = False
                for r in data["resources"]:
                    is_schema = parse_resource_if_schema(
                        catalog, r, item, orga, is_schema
                    )

                if not is_schema:
                    schema_suspicion(catalog, item, orga)
            except:
                pass


def publish_mattermost(ti):
    nb_datasets = float(ti.xcom_pull(key="nb", task_ids="check_new_datasets"))
    datasets = ti.xcom_pull(key="datasets", task_ids="check_new_datasets")
    nb_reuses = float(ti.xcom_pull(key="nb", task_ids="check_new_reuses"))
    reuses = ti.xcom_pull(key="reuses", task_ids="check_new_reuses")
    nb_orgas = float(ti.xcom_pull(key="nb", task_ids="check_new_orgas"))
    orgas = ti.xcom_pull(key="organizations", task_ids="check_new_orgas")

    if nb_datasets > 0:
        for item in datasets:
            message = (
                ":loudspeaker: :label: Nouveau **Jeu de données** : "
                f"*{item['name']}* \n\n\n:point_right: {item['page']}"
            )
            send_message(message, MATTERMOST_DATAGOUV_ACTIVITES)

    if nb_orgas > 0:
        for item in orgas:
            message = (
                ":loudspeaker: :office: Nouvelle **organisation** : "
                f"*{item['name']}* \n\n\n:point_right: {item['page']}"
            )
            send_message(message, MATTERMOST_DATAGOUV_ACTIVITES)

    if nb_reuses > 0:
        for item in reuses:
            message = (
                ":loudspeaker: :art: Nouvelle **réutilisation** : "
                f"*{item['name']}* \n\n\n:point_right: {item['page']}"
            )
            send_message(message, MATTERMOST_DATAGOUV_ACTIVITES)


default_args = {"email": ["geoffrey.aldebert@data.gouv.fr"], "email_on_failure": True}

with DAG(
    dag_id=DAG_NAME,
    schedule_interval="42 * * * *",
    start_date=days_ago(0, hour=1),
    dagrun_timeout=timedelta(minutes=60),
    tags=["notification", "hourly", "datagouv", "activite", "schemas"],
    default_args=default_args,
    catchup=False,
) as dag:
    check_new_datasets = PythonOperator(
        task_id="check_new_datasets",
        python_callable=check_new,
        templates_dict={"type": "datasets"},
    )

    check_new_reuses = PythonOperator(
        task_id="check_new_reuses",
        python_callable=check_new,
        templates_dict={"type": "reuses"},
    )

    check_new_orgas = PythonOperator(
        task_id="check_new_orgas",
        python_callable=check_new,
        templates_dict={"type": "organizations"},
    )

    publish_mattermost = PythonOperator(
        task_id="publish_mattermost",
        python_callable=publish_mattermost,
    )

    check_schema = PythonOperator(
        task_id="check_schema",
        python_callable=check_schema,
    )

    (
        [check_new_datasets, check_new_reuses, check_new_orgas]
        >> publish_mattermost
        >> check_schema
    )
