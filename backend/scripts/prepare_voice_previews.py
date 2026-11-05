"""Generate each fixed voice sample once; --generate is required to spend money.

An intent is fsynced before POST. Unknown attempts are never automatically retried.
Completed audio can be recovered locally after interruption without another POST.
"""

import argparse
import json
import os
import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import Settings
from app.errors import ApiError
from app.video_template_media import audio_duration
from app.video_tts import synthesize
from app.video_voice_catalog import VOICES, preview_path, tao_ready

SAMPLES = {
    "中文 (普通话)": "你好，欢迎试听我的声音。用自然的表达，讲好每一个故事。",  # noqa: E501
    "中文 (粤语)": "你好，欢迎试听我嘅声音。用自然嘅表达，讲好每一个故事。",  # noqa: E501
    "英文": "Hello, welcome to my voice preview. Let every story come to life naturally.",  # noqa: E501
    "日文": "こんにちは、私の声をお聴きください。自然な表現で、一つひとつの物語を伝えます。",  # noqa: E501
    "韩文": "안녕하세요, 제 목소리를 들어 보세요. 자연스러운 표현으로 모든 이야기를 전합니다.",  # noqa: E501
    "法文": "Bonjour, découvrez ma voix. Une expression naturelle pour raconter chaque histoire.",  # noqa: E501
    "德文": "Hallo, hören Sie meine Stimme. Mit natürlichem Ausdruck wird jede Geschichte lebendig.",  # noqa: E501
    "西班牙文": "Hola, escucha mi voz. Una expresión natural para contar cada historia.",  # noqa: E501
    "葡萄牙文": "Olá, ouça a minha voz. Uma expressão natural para contar cada história.",  # noqa: E501
    "意大利文": "Ciao, ascolta la mia voce. Un'espressione naturale per raccontare ogni storia.",  # noqa: E501
    "俄文": "Здравствуйте, послушайте мой голос. Естественное звучание для каждой истории.",  # noqa: E501
    "乌克兰文": "Вітаю, послухайте мій голос. Природне звучання для кожної історії.",  # noqa: E501
    "阿拉伯文": "مرحباً، استمع إلى صوتي. تعبير طبيعي يروي كل قصة.",  # noqa: E501
    "土耳其文": "Merhaba, sesimi dinleyin. Her hikayeyi doğal bir ifadeyle anlatın.",  # noqa: E501
    "荷兰文": "Hallo, luister naar mijn stem. Een natuurlijke klank voor ieder verhaal.",  # noqa: E501
    "越南文": "Xin chào, mời bạn nghe giọng nói của tôi. Kể mỗi câu chuyện thật tự nhiên.",  # noqa: E501
    "印尼文": "Halo, dengarkan suara saya. Ekspresi alami untuk menceritakan setiap kisah.",  # noqa: E501
    "泰文": "สวัสดี ลองฟังเสียงของฉัน ถ่ายทอดทุกเรื่องราวด้วยน้ำเสียงที่เป็นธรรมชาติ",  # noqa: E501
    "波兰文": "Witaj, posłuchaj mojego głosu. Naturalne brzmienie każdej opowieści.",  # noqa: E501
    "罗马尼亚文": "Bună, ascultă vocea mea. O expresie naturală pentru fiecare poveste.",  # noqa: E501
    "希腊文": "Γεια σας, ακούστε τη φωνή μου. Φυσική έκφραση για κάθε ιστορία.",  # noqa: E501
    "捷克文": "Dobrý den, poslechněte si můj hlas. Přirozený projev pro každý příběh.",  # noqa: E501
    "芬兰文": "Hei, kuuntele ääntäni. Luonnollinen ilmaisu herättää jokaisen tarinan eloon.",  # noqa: E501
    "印地文": "नमस्ते, मेरी आवाज़ सुनिए। हर कहानी को सहज अंदाज़ में कहिए।",  # noqa: E501
}


def write_report(path, data):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    temporary.replace(path)


def prepare(
    settings, *, generate=False, limit=None, keys=None, max_estimate=Decimal("3")
):
    selected = [(k, v) for k, v in VOICES.items() if keys is None or k in keys]
    if limit:
        selected = selected[:limit]
    pending = [(k, v) for k, v in selected if not preview_path(settings, k).is_file()]
    estimate = sum(
        Decimal(len(SAMPLES[v["language"]]))
        * (
            Decimal("0.00012")
            if settings.video_tao_tts_model == "speech-2.8-turbo"
            else Decimal("0.00021")
        )
        for _, v in pending
    )
    print(
        json.dumps(
            {
                "selected": len(selected),
                "cached": len(selected) - len(pending),
                "pending": len(pending),
                "estimated_cny": str(estimate),
                "generate": generate,
            }
        ),
        flush=True,
    )
    if not generate:
        return
    if not tao_ready(settings):
        raise SystemExit("Tao TTS is not configured/enabled.")
    if estimate > max_estimate:
        raise SystemExit("Estimate exceeds this run's budget; choose a smaller batch.")
    for key, voice in pending:
        target = preview_path(settings, key)
        target.parent.mkdir(parents=True, exist_ok=True)
        report = target.with_suffix(".json")
        intent = target.with_suffix(".intent")
        staged = target.with_suffix(".pending.mp3")
        if staged.is_file():
            seconds = audio_duration(staged)
            staged.replace(target)
            write_report(
                report,
                {
                    "status": "completed",
                    "duration_seconds": seconds,
                    "billing_status": "unreconciled",
                },
            )
            print(json.dumps({"voice": key, "status": "recovered"}), flush=True)
            continue
        if intent.exists():
            print(
                json.dumps(
                    {"voice": key, "status": "previous_attempt_requires_review"}
                ),
                flush=True,
            )
            continue
        text = SAMPLES[voice["language"]]
        selection = {
            "provider": "tao",
            "model": settings.video_tao_tts_model,
            "voice_id": voice["voice_id"],
            "speed": 1,
            "emotion": None,
            "language_boost": "auto",
        }
        try:
            with intent.open("x", encoding="utf-8") as marker:
                json.dump(
                    {
                        "voice_id": voice["voice_id"],
                        "model": selection["model"],
                        "text": text,
                    },
                    marker,
                    ensure_ascii=False,
                )
                marker.flush()
                os.fsync(marker.fileno())
        except FileExistsError:
            continue
        try:
            receipt = synthesize(settings, selection, text, staged)
            seconds = audio_duration(staged)
            staged.replace(target)
            write_report(
                report,
                {
                    "status": "completed",
                    "voice_id": voice["voice_id"],
                    "text": text,
                    "duration_seconds": seconds,
                    "receipt": receipt,
                },
            )
            print(
                json.dumps(
                    {"voice": key, "status": "completed", "duration_seconds": seconds}
                ),
                flush=True,
            )
        except Exception as error:
            code = (
                error.code
                if isinstance(error, ApiError)
                else "PREVIEW_VALIDATION_FAILED"
            )
            write_report(report, {"status": "requires_review", "error_code": code})
            print(
                json.dumps(
                    {"voice": key, "status": "requires_review", "error_code": code}
                ),
                flush=True,
            )
            # Stop on the first failure; do not burn through quota on a broken adapter.
            break


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--generate", action="store_true")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--voice", action="append")
    parser.add_argument("--max-estimate-cny", type=Decimal, default=Decimal("3"))
    args = parser.parse_args()
    prepare(
        Settings(_env_file=Path(__file__).resolve().parents[1] / ".env"),
        generate=args.generate,
        limit=args.limit,
        keys=args.voice,
        max_estimate=args.max_estimate_cny,
    )
