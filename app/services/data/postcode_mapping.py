"""Postcode to netbeheerder mapping for the Netherlands."""

from app.models.enrichment import Netbeheerder


def get_netbeheerder(postcode: str) -> Netbeheerder:
    """
    Bepaal netbeheerder op basis van postcode.

    Postcodegebieden Nederland:
    - 10-19: Noord-Holland → Liander
    - 20-29: Zuid-Holland → Stedin (deels Liander)
    - 30-39: Utrecht → Stedin
    - 40-49: Noord-Brabant West → Enexis
    - 50-59: Noord-Brabant Oost/Limburg → Enexis
    - 60-69: Limburg → Enexis
    - 70-79: Gelderland/Overijssel → Liander/Enexis
    - 80-89: Friesland → Liander
    - 90-99: Groningen/Drenthe → Enexis
    """
    # Extract first 4 digits
    pc_str = "".join(filter(str.isdigit, postcode))[:4]
    if len(pc_str) < 4:
        return Netbeheerder.LIANDER  # Default

    pc = int(pc_str)
    prefix = pc // 100

    # Specifieke uitzonderingen
    WESTLAND_POSTCODES = range(2670, 2700)
    COTEQ_POSTCODES = list(range(7540, 7560)) + list(range(7740, 7770))
    RENDO_POSTCODES = range(7900, 7920)

    if pc in WESTLAND_POSTCODES:
        return Netbeheerder.WESTLAND
    if pc in COTEQ_POSTCODES:
        return Netbeheerder.COTEQ
    if pc in RENDO_POSTCODES:
        return Netbeheerder.RENDO

    # Hoofdverdeling
    if prefix in [10, 11, 12, 13, 14, 15, 16, 17, 18, 19]:
        return Netbeheerder.LIANDER  # Noord-Holland
    elif prefix in [20, 21, 22, 23, 24, 25, 26, 27, 28, 29]:
        # Zuid-Holland: Stedin, behalve Haarlem/Leiden gebied (Liander)
        if prefix in [20, 21, 22, 23]:
            return Netbeheerder.LIANDER
        return Netbeheerder.STEDIN
    elif prefix in [30, 31, 32, 33, 34, 35, 36, 37, 38, 39]:
        # Utrecht: mix Stedin/Liander
        if prefix in [38, 39]:
            return Netbeheerder.LIANDER
        return Netbeheerder.STEDIN
    elif prefix in [40, 41, 42, 43, 44, 45, 46, 47, 48, 49]:
        return Netbeheerder.ENEXIS  # Noord-Brabant
    elif prefix in [50, 51, 52, 53, 54, 55, 56, 57, 58, 59]:
        return Netbeheerder.ENEXIS  # Noord-Brabant/Limburg
    elif prefix in [60, 61, 62, 63, 64, 65, 66, 67, 68, 69]:
        return Netbeheerder.ENEXIS  # Limburg
    elif prefix in [70, 71, 72, 73, 74, 75, 76, 77, 78, 79]:
        # Gelderland/Overijssel: Liander dominant
        if prefix in [74, 75, 76, 77]:
            return Netbeheerder.ENEXIS  # Overijssel deel
        return Netbeheerder.LIANDER
    elif prefix in [80, 81, 82, 83, 84, 85, 86, 87, 88, 89]:
        return Netbeheerder.LIANDER  # Friesland/Flevoland
    elif prefix in [90, 91, 92, 93, 94, 95, 96, 97, 98, 99]:
        return Netbeheerder.ENEXIS  # Groningen/Drenthe

    return Netbeheerder.LIANDER  # Default
