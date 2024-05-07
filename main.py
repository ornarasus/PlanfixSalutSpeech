import json
import os.path
import time
from datetime import datetime
import uuid
import requests

planfix_username: str
planfix_token: str
speech_token: str
speech_expires: int
salut_auth: str

lastComments = {}
if os.path.exists("lastComments.json"):
    with open("lastComments.json", "r") as fp:
        lastComments = json.load(fp)

print(lastComments)

def oauth2():
    global speech_token, speech_expires
    req = requests.post(
        "https://ngw.devices.sberbank.ru:9443/api/v2/oauth",
        data="scope=SALUTE_SPEECH_PERS",
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Authorization": f"Basic {salut_auth}",
            "RqUID": str(uuid.uuid4())
        },
        verify="rus.cer"
    )
    print(req.content)
    resp = json.loads(req.content)
    speech_token = resp["access_token"]
    speech_expires = resp["expires_at"]


def get_task() -> list[str]:
    req = requests.post(
        f"https://{planfix_username}.planfix.ru/rest/task/list",
        data='{"filters": [{"type": 10, "operator": "equal", "value": 2}]}',
        headers={
            "Authorization": f"Bearer {planfix_token}",
            "accept": "application/json",
            "Content-Type": "application/json"
        }
    )
    print(req.content)
    if req.status_code == 200:
        tasks = []
        resp = json.loads(req.content)
        for task in resp['tasks']:
            tasks.append(task["id"])
        return tasks


def get_comments(task_id: str) -> list[str]:
    global lastComments
    req = requests.post(
        f"https://{planfix_username}.planfix.ru/rest/task/{task_id}/comments/list",
        data="{}",
        headers={"Authorization": f"Bearer {planfix_token}"}
    )
    print(req.content)
    if req.status_code == 200:
        comments = []
        resp = json.loads(req.content)
        for comment in resp['comments']:
            if task_id in lastComments.keys():
                print(str(comment["id"]) == lastComments[task_id])
                if str(comment["id"]) == lastComments[task_id]:
                    break
            comments.append(comment["id"])
        lastComments[task_id] = str(resp['comments'][0]["id"])
        with open("lastComments.json", "w") as fp:
            json.dump(lastComments, fp)
        return comments


def get_audios(comment_id: str) -> list[str] | None:
    req = requests.get(
        f"https://{planfix_username}.planfix.ru/rest/comment/{comment_id}?fields=task%2C%20dataTags%2C%20files",
        headers={"Authorization": f"Bearer {planfix_token}"}
    )
    print(req.content)
    resp = json.loads(req.content)
    if req.status_code == 200 and len(resp["comment"]["dataTags"]) > 0 and \
            resp["comment"]["dataTags"][0]["dataTag"]["name"] == "Звонок":
        files = []
        for _file in resp["comment"]["files"]:
            files.append(_file["id"])
        return files


def download_audio(file_id: str) -> bytes:
    req = requests.get(
        f"https://{planfix_username}.planfix.ru/rest/file/{file_id}/download",
        headers={"Authorization": f"Bearer {planfix_token}"}
    )
    print(req.content)
    return req.content


def upload_audio(audio: bytes) -> str | None:
    req = requests.post(
        "https://smartspeech.sber.ru/rest/v1/data:upload",
        files={"audio": audio},
        headers={"Authorization": f"Bearer {speech_token}"},
        verify="rus.cer"
    )
    print(req.content)
    if req.status_code == 200:
        return json.loads(req.content)["result"]["request_file_id"]


def create_task(file_id: str) -> str | None:
    req = requests.post(
        "https://smartspeech.sber.ru/rest/v1/speech:async_recognize",
        verify="rus.cer",
        headers={"Authorization": f"Bearer {speech_token}"},
        data=json.dumps({
            "request_file_id": file_id,
            "options": {
                "language": "ru-RU",
                "audio_encoding": "MP3"
            }
        })
    )
    print(req.content)
    if req.status_code == 200:
        return json.loads(req.content)["result"]["id"]


def check_status(task_id: str) -> str | None:
    req = requests.get(
        f"https://smartspeech.sber.ru/rest/v1/task:get?id={task_id}",
        headers={"Authorization": f"Bearer {speech_token}"},
        verify="rus.cer"
    )
    print(req.content)
    resp = json.loads(req.content)
    if resp["result"]["status"] == "DONE":
        return resp["result"]["response_file_id"]


def get_script(file_id: str) -> str:
    req = requests.get(
        f"https://smartspeech.sber.ru/rest/v1/data:download?response_file_id={file_id}",
        headers={"Authorization": f"Bearer {speech_token}"},
        verify="rus.cer"
    )
    text: str = ""
    results = json.loads(req.content.decode(encoding="utf8"))
    for index in range(len(results)):
        if results[index]["results"][0]["normalized_text"] == "" or index == len(results)-1:
            continue
        text += f'<p>{results[index]["results"][0]["normalized_text"]}</p>'
    return text.replace('"', '\\"')


def update_comment(task_id: str, comment_id: str, text: str):
    req = requests.post(
        f"https://{planfix_username}.planfix.ru/rest/task/{task_id}/comments/{comment_id}",
        data=json.dumps({
            "description": text
        }),
        # f'{{"description": "{text}"}}'
        headers={
            "Authorization": f"Bearer {planfix_token}",
            "accept": "*/*",
            "Content-Type": "application/json"
        }
    )
    print(req.content)


def nowToUnix():
    return (datetime.now() - datetime(1970, 1, 1)).total_seconds()


oauth2()
while True:
    for task in get_task():
        for comment in get_comments(task):
            files = get_audios(comment)
            if files is None:
                continue
            for file in files:
                audio = download_audio(file)
                if speech_expires <= nowToUnix():
                    oauth2()
                audio_id = upload_audio(audio)
                if audio_id is None:
                    continue
                if speech_expires <= nowToUnix():
                    oauth2()
                task_id = create_task(audio_id)
                if task_id is None:
                    continue
                if speech_expires <= nowToUnix():
                    oauth2()
                while not check_status(task_id):
                    time.sleep(1)
                if speech_expires <= nowToUnix():
                    oauth2()
                script_id = check_status(task_id)
                if speech_expires <= nowToUnix():
                    oauth2()
                script = get_script(script_id)
                update_comment(task, comment, script)
    time.sleep(60)
