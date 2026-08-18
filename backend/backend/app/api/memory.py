"""Phase 7 — long-term memory API: saved queries and user preferences.

Deliberately separate from `chat.py`/session-scoped conversation memory —
these endpoints are opt-in actions (a user explicitly saving a query or
setting a preference), not part of the main ask() pipeline.

`user_id` here is a caller-supplied identifier (e.g. a stable browser/device
ID the frontend generates and persists locally), not an authenticated user
account — this project has no auth layer. Treat it as a namespacing key,
not a security boundary.
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services.long_term_memory import long_term_memory
from app.schemas.memory import (
    SaveQueryRequest,
    SavedQueryResponse,
    SetPreferenceRequest,
    PreferencesResponse,
)

router = APIRouter(prefix="/memory", tags=["memory"])


@router.post("/queries", response_model=SavedQueryResponse)
async def save_query(request: SaveQueryRequest):
    if not request.user_id or not request.question or not request.sql:
        raise HTTPException(status_code=400, detail="user_id, question, and sql are required")
    saved = long_term_memory.save_query(request.user_id, request.question, request.sql, request.label or "")
    return SavedQueryResponse(**saved.to_dict())


@router.get("/queries", response_model=list[SavedQueryResponse])
async def list_queries(user_id: str):
    saved = long_term_memory.list_saved_queries(user_id)
    return [SavedQueryResponse(**q.to_dict()) for q in saved]


@router.delete("/queries/{query_id}")
async def delete_query(query_id: str, user_id: str):
    deleted = long_term_memory.delete_saved_query(user_id, query_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Saved query not found")
    return {"status": "deleted"}


@router.put("/preferences")
async def set_preference(request: SetPreferenceRequest):
    if not request.user_id or not request.key:
        raise HTTPException(status_code=400, detail="user_id and key are required")
    long_term_memory.set_preference(request.user_id, request.key, request.value)
    return {"status": "saved"}


@router.get("/preferences", response_model=PreferencesResponse)
async def get_preferences(user_id: str):
    prefs = long_term_memory.get_preferences(user_id)
    return PreferencesResponse(preferences=prefs)


class TonePreviewRequest(BaseModel):
    language: str = "auto"
    arabic_dialect: str = "egyptian"
    report_tone: str = "executive"


@router.post("/preferences/preview")
async def preview_tone_and_dialect(req: TonePreviewRequest):
    """Generate a sample greeting and report snippet demonstrating the configured dialect and tone."""
    is_ar = req.language == "ar" or (req.language == "auto")

    if req.language == "en":
        if req.report_tone == "technical":
            sample = "Executive Technical Overview: Query scan across 1,420 rows indicates an R² correlation of 0.89 between latency and token cost."
        elif req.report_tone == "concise":
            sample = "• Query returned 1,420 rows.\n• Key trend: Token cost correlates directly with query latency.\n• Recommendation: Enforce read-only scan limits."
        else:
            sample = "Here is the executive summary of your query results: Overall execution efficiency remains optimal across all 1,420 database records analyzed today."
    else:
        dialect_map = {
            "egyptian": {
                "executive": "أهلاً بيك يا فندم! ملخص التحليل المالي والبياني السريع لليوم بيوضح إن معظم استهلاك التوكنز في نطاق ممتاز جداً بدون أي تجاوز للحدود.",
                "technical": "تقرير فني مفصل (لهجة مصرية): تم تحليل 1,420 سجل بنظام الـ scan، واكتشفنا معامل ارتباط 0.89 بين استهلاك الميموري والـ LLM.",
                "concise": "• تم فحص 1,420 صف.\n• الوضع الحالي الممتاز: الأداء مستقر ومفيش استهلاك زائد في التوكنز.\n• التوصية: استمرار العمل بنظام حماية البيانات.",
            },
            "gulf": {
                "executive": "يا هلا ومرحبا فيك! موجز التقرير التنفيذي يوضح ما شاء الله إن استهلاك البيانات ممتاز والنتائج متوافقة مع معايير الأمان.",
                "technical": "تحليل تقني دقيق (لهجة خليجية): تم مراجعة 1,420 استعلام، ومؤشرات الأداء تدل على كفاءة استهلاك التوكنز بنسبة 99.4% بدون تأخير.",
                "concise": "• استرجاع 1,420 سجل.\n• المؤشر الرئيسي: كفاءة تشغيلية عالية واستهلاك ممتاز.\n• الإجراء المطلوب: الحفاظ على نفس الإعدادات.",
            },
            "levantine": {
                "executive": "أهلين فيك! ملخص التقرير اليوم بيظهر إنه كل نتائج البحث طالعة ممتازة ومضبوطة كتير بدون أي مشاكل بالأداء أو استهلاك التوكنز.",
                "technical": "تقرير تقني مفصل (لهجة شامية): فحصنا 1,420 سجل، ولقينا تناغم كامل بمعدل استجابة النظام (0.39 ثانية) وبأعلى دقة ممكنة.",
                "concise": "• تم التدقيق بـ 1,420 صف.\n• الخلاصة: الأمور كلها تمام وسرعة الاستجابة عالية.\n• التوصية: متابعة العمل على نفس الهيكلية.",
            },
            "north_african": {
                "executive": "مرحباً بيك! ملخص التقرير التحليلي يوضح باللي كل مؤشرات الأداء والتوكنز راهي في المستوى المطلوب وبدون أي تجاوز.",
                "technical": "تحليل فني معمق: تم فحص 1,420 سجل، والنتائج تبين فاعلية عالية في معالجة البيانات واستقرار في زمن الاستجابة.",
                "concise": "• مراجعة 1,420 صف.\n• الوضعية الحالية: أداء مستقر وفعال جداً.\n• التوصية: استمرار المراقبة الآلية.",
            },
            "msa": {
                "executive": "أهلاً بك. يُظهر الموجز التنفيذي لتحليل قاعدة البيانات استقراراً ممتازاً في الأداء مع التزام كامل بضمانات ومحددات استهلاك التشفير.",
                "technical": "التقرير التقني المفصل: تمت معالجة 1,420 سجلاً بقاعدة البيانات؛ أظهرت المقاييس كفاءة استجابة تبلغ 391 مللي ثانية بدقة استرداد 99.9%.",
                "concise": "• تم استرداد وتحليل 1,420 سجلاً.\n• المؤشر الأساسي: كفاءة الأداء التشغيلي واستهلاك مثالي للوحدات.\n• التوصية: المداومة على إعدادات الحماية الحالية.",
            }
        }
        d_samples = dialect_map.get(req.arabic_dialect, dialect_map["msa"])
        sample = d_samples.get(req.report_tone, d_samples["executive"])

    return {
        "preview_text": sample,
        "language_detected": "Arabic (العربية)" if is_ar else "English",
        "dialect": req.arabic_dialect,
        "tone": req.report_tone,
        "status": "success"
    }

