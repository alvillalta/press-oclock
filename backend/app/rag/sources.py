from typing import List

from app.core.logging import get_logger
from app.models import AugmentedMailChunksGroup, Chunk, Sources

logger = get_logger(__name__)

def get_sources(
    similar_chunks: List[Chunk], 
    augmented_chunks: List[AugmentedMailChunksGroup]
) -> List[Sources]:
    """
    Combina los chunks recuperados originalmente con los metadatos de su correo asociado.
    """
    # Indice de metadatos por mail_id usando augmented_chunks
    by_augmented_chunks = {}

    for information_group in augmented_chunks:
        mail_id = information_group["mail_id"]
        by_augmented_chunks[mail_id] = {
            "subject": information_group["subject"],
            "sender": information_group["sender"],
            "date": information_group["date"],
        }

    # content desde similar_chunks + metadata desde augmented_chunks
    sources: List[Sources] = []

    for chunk in similar_chunks:

        mail_metadata = by_augmented_chunks.get(chunk.mail_id)

        sources.append(
            Sources(
                mail_id=chunk.mail_id,
                content=chunk.content,
                subject=mail_metadata["subject"] if mail_metadata else None,
                sender=mail_metadata["sender"],
                date=mail_metadata["date"]
            )
        )

    return sources

[{"subject": "Fwd: 'La bola negra', 'Los domingos' y 'El ser querido', preseleccionadas para representar a Espa\u00f1a en los Oscar", "sender": "pressoclock@gmail.com", "date": "2026-09-24T14:55:58Z", "mail_id": "dea1f4d2-e4b5-4245-afb6-215e9958477d", "content": "---------- Forwarded message ---------\r\nFrom: Arturo Luis Villalta L\u00f3pez <alvillalt@gmail.com>\r\nDate: Thu, Sep 3, 2026 at 8:29\u202fPM\r\nSubject: 'La bola negra', 'Los domingos' y 'El ser querido',\r\npreseleccionadas para representar a Espa\u00f1a en los Oscar\r\nTo: <pressoclock@gmail.com>\r\n\r\n\r\n2026 no ha sido un a\u00f1o cualquiera para el cine espa\u00f1ol y como prueba el\r\npeso de las tres pel\u00edculas preseleccionadas por la Academia de Cine para\r\nrepresentar a Espa\u00f1a en los Oscar 2027 en la categor\u00eda de mejor pel\u00edcula\r\ninternacional. Los domingos, de Alauda Ruiz de Az\u00faa; La bola negra, de\r\nJavier Calvo y Javier Ambrossi; y El ser querido, de Rodrigo Sorogoyen, son\r\nlas tres pel\u00edculas m\u00e1s votadas para los acad\u00e9micos: las tres podr\u00edan haber\r\nsido indiscutibles otro a\u00f1o y ahora vuelven a competir en una segunda r"}, {"subject": "Fwd: 'La bola negra', 'Los domingos' y 'El ser querido', preseleccionadas para representar a Espa\u00f1a en los Oscar", "sender": "pressoclock@gmail.com", "date": "2026-09-24T14:55:58Z", "mail_id": "dea1f4d2-e4b5-4245-afb6-215e9958477d", "content": " Luengo, en el contexto del rodaje de una pel\u00edcula\r\nen el desierto canario. Presente tambi\u00e9n en el Festival de Cannes, su mayor\r\naval en la carrera de los Oscar es la presencia de Bardem, estrella mundial\r\nya nominada -y ganadora- del Oscar.\r\n\r\nEl largo reencuentro entre un padre ausente (un aclamado director de cine)\r\ny una hija (actriz sin \u00e9xito) tras d\u00e9cadas sin verse, le sirve a Sorogoyen\r\npara bosquejar un gran vac\u00edo contado desde los silencios. La idea que\r\nsobrevuela es que la madeja de versiones del pasado quiz\u00e1 sea tan\r\nirresoluble que la reparaci\u00f3n no puede venir del perd\u00f3n o la verdad, sino\r\ntan solo de la comprensi\u00f3n del dolor del otro.\r\n\r\nLos domingos\r\nY, respecto a Los domingos"}, {"subject": "Fwd: 'La bola negra', 'Los domingos' y 'El ser querido', preseleccionadas para representar a Espa\u00f1a en los Oscar", "sender": "pressoclock@gmail.com", "date": "2026-09-24T14:55:58Z", "mail_id": "dea1f4d2-e4b5-4245-afb6-215e9958477d", "content": " que\r\ntrata de desactivar la vocaci\u00f3n mientras sufre en su propia relaci\u00f3n de\r\npareja y mantiene tiranteces con su hermano por la herencia familiar.\r\n\r\nUna historia contada con una honestidad total hacia sus protagonistas hasta\r\nel punto de diluir completamente la postura de su autora. Recibida\r\nsimult\u00e1neamente como una retrato de la vocaci\u00f3n o como una disecci\u00f3n de la\r\nopresi\u00f3n religiosa seg\u00fan el espectador, la directora aclar\u00f3 al recibir el\r\npremio Forqu\u00e9 el pasado diciembre :\"Los domingos es una pel\u00edcula que\r\nexplora c\u00f3mo el adoctrinamiento religioso puede distorsionar tu percepci\u00f3n\r\no tus sentimientos\".\r\n\r\nLa 99 edici\u00f3n de los Premios Oscar se celebrar\u00e1 el pr\u00f3ximo 14 de marzo en\r\nel Dolb"}]