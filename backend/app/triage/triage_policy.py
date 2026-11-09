from dataclasses import dataclass
from typing import Literal

# Preguntas
BODY_SUFFICIENCY_QUESTION_ID = "body_sufficient"
RISK_QUESTION_IDS = ("is_spam", "is_toxic", "is_hazard")

# Umbrales
DEFAULT_RISK_THRESHOLD = 0.7
DEFAULT_RISK_REVIEW_THRESHOLD = 0.3
DEFAULT_MIN_BODY_SUFFICIENCY = 0.3

# Literal restringe los valores posibles de un estado interno del triaje
TriageStatus = Literal["continue", "review", "blocked", "failed"]


@dataclass(frozen=True)
class MailTriageDecision:
    status: TriageStatus
    reason: str | None = None
    blocked_by: str | None = None


def decide_triage(
    probabilities: dict[str, float],
    *,
    risk_threshold: float = DEFAULT_RISK_THRESHOLD,
    review_threshold: float = DEFAULT_RISK_REVIEW_THRESHOLD,
    min_body_sufficiency: float = DEFAULT_MIN_BODY_SUFFICIENCY,
) -> MailTriageDecision:
    """Aplica las reglas del contrato del backend a las probabilidades de clasificación obtenidas."""

    # Se mantienen insertan por separado para las comprobaciones porque después se tratan con una lógica de negocio distinta
    required_question_ids = (
        BODY_SUFFICIENCY_QUESTION_ID,
        *RISK_QUESTION_IDS,
    )  # El asterisco desempaqueta cada elemento de la tupla como uno de la nueva tupla

    # Comprueba que las preguntas obtenidas se correspondan con las esperadas
    if any(question_id not in probabilities for question_id in required_question_ids):
        return MailTriageDecision(status="failed", reason="invalid_jev_response")

    body_sufficiency = probabilities[BODY_SUFFICIENCY_QUESTION_ID]
    risk_probabilities = {
        question_id: probabilities[question_id] for question_id in RISK_QUESTION_IDS
    }

    # Comprueba que los valores sean normativos
    if not all(
        0.0 <= probability <= 1.0
        for probability in (body_sufficiency, *risk_probabilities.values())
    ):
        return MailTriageDecision(status="failed", reason="invalid_jev_response")

    # Comprueba que el texto sea suficiente para el análisis
    if body_sufficiency <= min_body_sufficiency:
        return MailTriageDecision(status="review", reason="insufficient_body")

    # Crea un diccionario con las parejas question_id-valor que supera el umbral de riesgo
    blocking_risks = {
        question_id: probability
        for question_id, probability in risk_probabilities.items()
        if probability > risk_threshold
    }
    if blocking_risks:
        # .max() también sirve para iterar sobre objetos y la key le indica lo que tiene que comparar (los valores de las claves en este caso). Lambda pasa la clave como argumento y devuelve su valor
        blocked_by = max(
            blocking_risks, key=lambda question_id: blocking_risks[question_id]
        )
        return MailTriageDecision(
            status="blocked",
            reason="risk_detected",
            blocked_by=blocked_by,
        )

    # De los valores de las question_id, si existe cualquiera entre los umbrales de revisión y riesgo lo marca como "review"
    if any(
        review_threshold <= probability <= risk_threshold
        for probability in risk_probabilities.values()
    ):
        return MailTriageDecision(status="review", reason="uncertain_risk")

    return MailTriageDecision(status="continue")
