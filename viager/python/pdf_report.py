"""Private, in-memory French PDF report for a validated Viager Studio result.

The renderer only formats the supplied result. It does not call the simulation
engine, read the original workbook, or contact any external service.
"""
from __future__ import annotations
import json

from datetime import datetime, timezone
from io import BytesIO
from math import isfinite
from pathlib import Path
from xml.sax.saxutils import escape, quoteattr
from zoneinfo import ZoneInfo

from reportlab.graphics.shapes import Drawing, Line, PolyLine, Rect, String
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import (
    HRFlowable, KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer,
    Table, TableStyle,
)

NAVY = colors.HexColor("#142C45")
TEAL = colors.HexColor("#087F83")
INK = colors.HexColor("#243447")
MUTED = colors.HexColor("#536575")
PALE = colors.HexColor("#F1F6F8")
LINE = colors.HexColor("#D9E4E8")
AMBER = colors.HexColor("#8A4D10")
PAPER_W, PAPER_H = A4
MARGIN = 17 * mm
CONTENT_W = PAPER_W - 2 * MARGIN


def _fonts():
    """Embed Arial when available, preserving French accents and the euro sign."""
    regular, bold = Path("C:/Windows/Fonts/arial.ttf"), Path("C:/Windows/Fonts/arialbd.ttf")
    if regular.exists() and bold.exists():
        try:
            if "VSArial" not in pdfmetrics.getRegisteredFontNames():
                pdfmetrics.registerFont(TTFont("VSArial", str(regular)))
                pdfmetrics.registerFont(TTFont("VSArialBold", str(bold)))
                pdfmetrics.registerFontFamily("VSArial", normal="VSArial", bold="VSArialBold", italic="VSArial", boldItalic="VSArialBold")
            return "VSArial", "VSArialBold"
        except (OSError, ValueError):
            pass
    return "Helvetica", "Helvetica-Bold"


def _number(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        value = float(value)
    except (ValueError, TypeError, OverflowError):
        return None
    return value if isfinite(value) else None


def _fmt(value, decimals=0, suffix=""):
    value = _number(value)
    if value is None:
        return "À confirmer"
    return f"{value:,.{decimals}f}".replace(",", " ").replace(".", ",") + suffix


def _eur(value, decimals=0):
    return _fmt(value, decimals, " €")


def _pct(value):
    value = _number(value)
    return _fmt(None if value is None else value * 100, 2, " %")


def _years(value):
    return _fmt(value, 1, " ans")


def _date(value):
    try:
        generated = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if generated.tzinfo is None:
            generated = generated.replace(tzinfo=timezone.utc)
        return generated.astimezone(ZoneInfo("Europe/Paris")).strftime("%d/%m/%Y à %H:%M")
    except (TypeError, ValueError):
        return "Date à confirmer"


def _safe(value):
    return escape(str(value if value is not None else "À confirmer")).replace("\n", "<br/>")


def _styles(font, bold):
    base = getSampleStyleSheet()
    result = {}
    for name, size, leading, color, extra in [
        ("title", 27, 32, NAVY, {"fontName": bold, "spaceAfter": 9}),
        ("subtitle", 12, 17, MUTED, {"spaceAfter": 12}),
        ("h1", 18, 23, NAVY, {"fontName": bold, "spaceAfter": 12}),
        ("h2", 12, 17, TEAL, {"fontName": bold, "spaceBefore": 11, "spaceAfter": 6}),
        ("body", 10, 14, INK, {"spaceAfter": 7}),
        ("small", 10, 13, MUTED, {"spaceAfter": 5}),
        ("warning", 10, 14, AMBER, {"spaceAfter": 6}),
        ("cell", 10, 13, INK, {}),
        ("cell_right", 10, 13, INK, {"alignment": TA_RIGHT}),
        ("table_head", 10, 12, colors.white, {"fontName": bold}),
        ("metric_label", 10, 13, MUTED, {}),
        ("metric_value", 18, 23, NAVY, {"fontName": bold}),
    ]:
        result[name] = ParagraphStyle(name, parent=base["Normal"], fontName=extra.pop("fontName", font), fontSize=size, leading=leading, textColor=color, **extra)
    return result


class _NumberedCanvas(Canvas):
    """Draw a stable page/total footer after the flowables have been laid out."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._states = []

    def showPage(self):
        self._states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        total = len(self._states)
        for state in self._states:
            self.__dict__.update(state)
            self.saveState()
            self.setStrokeColor(LINE)
            self.line(MARGIN, 15 * mm, PAPER_W - MARGIN, 15 * mm)
            self.setFont(_fonts()[0], 9)
            self.setFillColor(MUTED)
            self.drawString(MARGIN, 10.2 * mm, "Simulation privée - hypothèses, pas un gain réalisé")
            self.drawRightString(PAPER_W - MARGIN, 10.2 * mm, f"Page {self._pageNumber} / {total}")
            self.restoreState()
            super().showPage()
        super().save()


def _header(canvas, doc):
    canvas.saveState()
    canvas.setFont(_fonts()[1], 11)
    canvas.setFillColor(NAVY)
    canvas.drawString(MARGIN, PAPER_H - 13 * mm, "Viager Studio")
    canvas.setFont(_fonts()[0], 9)
    canvas.setFillColor(MUTED)
    canvas.drawRightString(PAPER_W - MARGIN, PAPER_H - 13 * mm, "Rapport de simulation | usage privé")
    canvas.setStrokeColor(TEAL)
    canvas.setLineWidth(1.3)
    canvas.line(MARGIN, PAPER_H - 17 * mm, PAPER_W - MARGIN, PAPER_H - 17 * mm)
    canvas.restoreState()


def _table(rows, widths, styles, header=True, right_from=1):
    body = []
    for index, row in enumerate(rows):
        body.append([
            Paragraph(_safe(value), styles["table_head"] if header and index == 0 else styles["cell_right"] if column >= right_from else styles["cell"])
            for column, value in enumerate(row)
        ])
    table = Table(body, colWidths=widths, repeatRows=1 if header else 0, hAlign="LEFT")
    commands = [
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LINEBELOW", (0, 0), (-1, -1), .35, LINE),
        ("ROWBACKGROUNDS", (0, 1 if header else 0), (-1, -1), [colors.white, PALE]),
    ]
    if header:
        commands.append(("BACKGROUND", (0, 0), (-1, 0), NAVY))
    table.setStyle(TableStyle(commands))
    return table


def _metrics(items, styles):
    cells = []
    for label, value in items:
        cells.append([
            Paragraph(_safe(label), styles["metric_label"]),
            Paragraph(_safe(value), styles["metric_value"]),
        ])
    while len(cells) % 2:
        cells.append("")
    rows = [cells[index:index + 2] for index in range(0, len(cells), 2)]
    table = Table(rows, colWidths=[CONTENT_W / 2] * 2)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), PALE),
        ("BOX", (0, 0), (-1, -1), .6, LINE),
        ("INNERGRID", (0, 0), (-1, -1), .6, LINE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 12),
        ("RIGHTPADDING", (0, 0), (-1, -1), 12),
        ("TOPPADDING", (0, 0), (-1, -1), 11),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 11),
    ]))
    return table


def _chart(flows, font):
    """Vector chart with honest independent series; missing values are skipped."""
    series = []
    for key, label, color in [
        ("cumulative_cost", "Coût net cumulé", TEAL),
        ("property_value", "Valeur projetée", NAVY),
    ]:
        data = [(float(row["year"]), _number(row.get(key))) for row in flows if _number(row.get("year")) is not None]
        data = [(year, amount) for year, amount in data if amount is not None]
        if data:
            series.append((label, color, data))
    if not series:
        return None
    drawing = Drawing(CONTENT_W, 222)
    left, bottom, width, height = 62, 35, CONTENT_W - 75, 148
    all_points = [point for _, _, data in series for point in data]
    low = min(0, min(amount for _, amount in all_points))
    high = max(0, max(amount for _, amount in all_points))
    if high == low:
        high = low + 1
    max_year = max(1, max(year for year, _ in all_points))
    for index in range(5):
        level = low + (high - low) * index / 4
        y = bottom + height * index / 4
        drawing.add(Line(left, y, left + width, y, strokeColor=LINE, strokeWidth=.5))
        drawing.add(String(left - 6, y - 3, _fmt(level / 1000, 0), fontName=font, fontSize=10, fillColor=MUTED, textAnchor="end"))
    drawing.add(String(8, bottom + height + 6, "k€", fontName=font, fontSize=10, fillColor=MUTED))
    for year in sorted(set([1, max(1, int(max_year / 2)), int(max_year)])):
        x = left + width * year / max_year
        drawing.add(String(x, bottom - 16, str(year), fontName=font, fontSize=10, fillColor=MUTED, textAnchor="middle"))
    drawing.add(String(left + width / 2, 3, "Année", fontName=font, fontSize=10, fillColor=MUTED, textAnchor="middle"))
    for index, (label, color, data) in enumerate(series):
        points = []
        for year, amount in data:
            points.extend([left + width * year / max_year, bottom + height * (amount - low) / (high - low)])
        if len(points) >= 4:
            drawing.add(PolyLine(points, strokeColor=color, strokeWidth=2))
        else:
            drawing.add(Rect(points[0] - 2, points[1] - 2, 4, 4, fillColor=color, strokeColor=color))
        x = 62 + index * 205
        drawing.add(Line(x, 210, x + 20, 210, strokeColor=color, strokeWidth=2))
        drawing.add(String(x + 26, 206, label, fontName=font, fontSize=10, fillColor=INK))
    return drawing


def build_pdf(result: dict) -> bytes:
    """Return an A4 PDF; absent/non-applicable metrics remain visibly unconfirmed."""
    font, bold = _fonts()
    styles = _styles(font, bold)
    result = result or {}
    inputs = result.get("inputs") or {}
    summary = result.get("summary") or {}
    flows = result.get("annual_flows") or []
    portage = result.get("mode", inputs.get("mode")) == "portage"
    story = []

    def p(text, style="body"):
        return Paragraph(_safe(text), styles[style])

    def section(text):
        story.append(p(text, "h2"))

    def pairs(items):
        table = _table(items, [CONTENT_W * .56, CONTENT_W * .44], styles, header=False)
        table.setStyle(TableStyle([("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]))
        story.append(table)

    def new_page(title):
        story.extend([PageBreak(), p(title, "h1")])

    story.append(p("Viager Studio", "title"))
    story.append(p(result.get("name") or inputs.get("name") or "Simulation immobilière", "subtitle"))
    kind = "Portage immobilier - rendement brut" if portage else "Viager " + {"occupe": "occupé", "libre": "libre"}.get(inputs.get("type"), "- type à confirmer")
    if inputs.get('contract_kind')=='vente-terme':
        kind='Vente à terme '+('libre' if inputs.get('type')=='libre' else 'occupée')+' - '+_fmt(inputs.get('payment_term_years'))+' ans de paiement'
    story.append(p(f"{kind} | Établi le {_date(result.get('generated_at'))}", "small"))
    story.append(p(f"Référentiel fiscal : {result.get('fiscal_year') or 'À confirmer'}. Montants en euros. Résultat fondé sur les données et hypothèses renseignées.", "small"))
    story.append(Spacer(1, 9))
    story.append(_metrics([
        ("Trésorerie initiale à mobiliser", _eur(summary.get("initial_cash"))),
        ("Effort mensuel - première année", _eur(summary.get("year1_monthly_effort"))),
        ("Coût net cumulé à l'horizon", _eur(summary.get("total_net_cost"))),
        ("Valeur projetée à l'horizon", _eur(summary.get("projected_value"))),
        ("Marge nominale théorique", _eur(summary.get("nominal_margin"))),
        ("TRI " + ("brut" if portage else "du scénario"), _pct(summary.get("irr"))),
    ], styles))
    section("Lire la synthèse")
    story.append(p("La marge nominale est une différence théorique à l'horizon. Elle ne constitue ni un gain réalisé ni une promesse de rendement. Les frais de cession et la fiscalité de la plus-value ne sont pas nécessairement déduits. Le détail des limites du moteur et des saisies figure ci-dessous.", "small"))
    if portage:
        story.append(p("Le rendement du portage est brut. Le taux renseigné ne permet pas de déduire une qualification fiscale ; un résultat net fiscal ne peut pas être validé sans connaître la nature juridique et fiscale des revenus.", "warning"))
    else:
        story.append(p("Le TRI et la VAN dépendent notamment de la durée de versement, de la libération, du financement et de la valeur de cession. Une rente toujours due à la sortie peut grever le prix de vente : le TRI net n'est pas validé lorsque cette valeur de cession est inconnue.", "small"))
    warnings = result.get("warnings") or []
    if warnings:
        section("Points de vigilance")
        for warning in warnings:
            story.append(p("• " + str(warning), "warning"))
    else:
        story.append(p("L'absence d'alerte fournie ne vaut pas validation notariale, fiscale ou financière.", "small"))

    glossary = json.loads((Path(__file__).resolve().parent / 'glossary.json').read_text(encoding='utf8'))
    for start, title in ((0, "Légende - lire les chiffres"), (6, "Légende - valeur et incertitude"), (12, "Légende - fiscalité et contrat")):
        new_page(title)
        story.append(p("Définitions et conseils de lecture. Les résultats restent liés aux hypothèses de la simulation.", "small"))
        for entry in glossary[start:start+6]:
            story.append(KeepTogether([p(entry['term'] + ' - ' + entry['name'], 'h2'), p(entry['definition'], 'small'), p(entry['reading'], 'small')]))

    new_page("Trajectoire financière")
    pairs([
        ("VAN au taux d'actualisation renseigné", _eur(summary.get("npv"))),
        ("Taux d'actualisation annuel", _pct(inputs.get("discount_rate"))),
        ("Effort mensuel moyen", _eur(summary.get("average_monthly_effort"))),
        ("Année d'équilibre du modèle", _fmt(summary.get("break_even_year"))),
        ("Capital emprunté restant à la sortie", _eur(summary.get("loan_remaining"))),
        ("Rendement net après libération", _pct(summary.get("net_yield_after_release"))),
    ])
    section("Coût cumulé et valeur immobilière")
    chart = _chart(flows, font)
    story.append(chart if chart else p("Courbe non disponible : flux annuels à confirmer."))
    story.append(p("La valeur est une hypothèse immobilière ; le coût net cumulé suit les flux calculés. Leur écart ne correspond pas au produit net d'une vente. Le crédit et la dette de sortie doivent être lus ensemble.", "small"))
    section("Flux cumulés du scénario")
    pairs([
        ("Rentes versées", _eur(summary.get("total_annuity"))),
        ("Loyers encaissés", _eur(summary.get("total_rent"))),
        ("Fiscalité calculée", _eur(summary.get("total_tax"))),
        ("Frais notariés retenus", _eur(summary.get("notary_fees"))),
    ])

    scenarios = result.get("scenarios") or []
    longevity, mc = result.get("longevity"), result.get("mc")
    if scenarios or not portage:
        new_page("Sensibilités et incertitude")
        story.append(p("Les scénarios font varier les hypothèses de durée. Les résultats restent des projections ; aucune probabilité de gain n'est déduite des seuls montants saisis."))
        if scenarios:
            section("Scénarios comparés")
            story.append(p("Durées en années ; VAN, coût net cumulé, marge nominale et effort mensuel en euros. La marge est théorique avant les frais et impôts de cession non inclus.", "small"))
            rows = [["Scénario", "Durée", "Libre après", "TRI brut" if portage else "TRI", "VAN", "Coût net", "Marge", "Effort / mois"]]
            for scenario in scenarios:
                rows.append([
                    scenario.get("name") or "Scénario", _fmt(scenario.get("death_after"), 1),
                    _fmt(scenario.get("libre_after"), 1), _pct(scenario.get("irr")),
                    _fmt(scenario.get("npv")), _fmt(scenario.get("total_net_cost")),
                    _fmt(scenario.get("nominal_margin")), _fmt(scenario.get("monthly_effort")),
                ])
            story.append(_table(rows, [90, 44, 48, 52, 70, 73, 72, CONTENT_W - 449], styles))
            story.append(p("La durée est celle des versements retenue dans le scénario (ou l'horizon en portage). La libération est une hypothèse distincte.", "small"))
        if not portage:
            section("Repères de longévité statistique")
            if longevity:
                pairs([
                    ("Durée moyenne statistique", _years(longevity.get("mean"))),
                    ("Durée médiane statistique", _years(longevity.get("median"))),
                    ("Longévité P10", _years(longevity.get("p10"))),
                    ("Longévité P90 - durée longue", _years(longevity.get("p90"))),
                ])
                story.append(p("Ces repères proviennent d'une table statistique et des paramètres saisis. Ils ne constituent pas une estimation médicale individuelle.", "small"))
            else:
                story.append(p("Non applicable : vente à terme, versements indépendants du décès." if inputs.get('contract_kind')=='vente-terme' else "Non calculée : renseigner âge et sexe.", "small"))
            section("Simulation Monte Carlo")
            if mc:
                pairs([
                    ("Nombre de tirages", _fmt(mc.get("draws"))),
                    ("Tirages avec TRI valide", _fmt(mc.get("valid_irr_draws"))),
                    ("Tirages avec rente active à la sortie", _fmt(mc.get("active_annuity_at_exit_draws"))),
                    ("TRI médian", _pct(mc.get("irr_median"))),
                    ("TRI P10 - rendement défavorable", _pct(mc.get("irr_p10"))),
                    ("TRI P90 - rendement élevé", _pct(mc.get("irr_p90"))),
                    ("VAN médiane", _eur(mc.get("npv_median"))),
                    ("Durée longue défavorable retenue", _years(mc.get("adverse_longevity_years"))),
                ])
                story.append(p("Les quantiles de TRI portent uniquement sur les tirages avec TRI valide. Les tirages avec rente active à la sortie sont comptés séparément : cette distribution conditionnelle ne décrit pas le rendement de l'ensemble des tirages.", "small"))
            elif inputs.get("heads"):
                story.append(p("Non calculée dans le résultat fourni ; vérifier les données de tête(s) et l'activation du calcul.", "small"))
            else:
                story.append(p("Non calculée : renseigner âge et sexe.", "small"))
            story.append(p("Longévité P90 signifie une durée statistique longue. TRI P10 signifie un rendement parmi les 10 % les plus faibles des tirages. Ce sont deux distributions différentes : ces valeurs ne sont pas interchangeables et ne décrivent pas forcément le même tirage.", "warning"))

    new_page("Hypothèses de la simulation")
    section("Opération et calendrier")
    operation = [
        ("Usage", {"habitation": "Habitation", "professionnel": "Professionnel"}.get(inputs.get("usage"), "À confirmer")),
        ("Valeur libre du bien", _eur(inputs.get("property_value"))),
        ("Valeur occupée", _eur(inputs.get("occupied_value"))),
        ("Bouquet", _eur(inputs.get("bouquet"))),
        ("Rente mensuelle initiale", _eur(inputs.get("monthly_annuity"))),
        ("Indexation annuelle de la rente", _pct(inputs.get("annuity_growth"))),
        ("Durée de versement retenue", _years(inputs.get("death_after"))),
        ("Libération / départ en établissement après", _years(inputs.get("libre_after"))),
        ("Majoration de rente à la libération", _pct(inputs.get("departure_increase"))),
        ("Horizon du modèle", _years(inputs.get("years"))),
        ("Croissance annuelle de la valeur", _pct(inputs.get("property_growth"))),
        ("Réversion entre têtes", _pct(inputs.get("reversal"))),
        ("Table de mortalité", inputs.get("mortality_table") or "À confirmer"),
        ("Coefficient de mortalité saisi", _fmt(inputs.get("mortality_adjustment"), 2)),
    ]
    if portage:
        operation = [
            ("Quote-part investie", _eur(inputs.get("share_investment"))),
            ("Coût total du projet", _eur(inputs.get("project_cost"))),
            ("Valeur totale du projet à la sortie", _eur(inputs.get("exit_project_value"))),
            ("Durée de détention", _years(inputs.get("holding_years"))),
            ("Rendement annuel brut saisi", _pct(inputs.get("annual_yield"))),
            ("Apport saisi", _eur(inputs.get("downpayment"))),
            ("Horizon du modèle", _years(inputs.get("years"))),
        ]
    pairs(operation)
    heads = inputs.get("heads") or []
    if heads and not portage:
        section("Paramètres statistiques saisis")
        for index, head in enumerate(heads, 1):
            story.append(p(f"Tête {index} : âge {_fmt(head.get('age'))} ans ; sexe {head.get('sex') or 'à confirmer'} ; année de naissance {_fmt(head.get('birth_year'))}.", "small"))
        story.append(p("Seuls les paramètres déclarés sont utilisés. Aucune hypothèse de santé individuelle n'est ajoutée au rapport.", "small"))

    section("Frais d'acquisition")
    pairs([
        ("Base des frais notariés", {"occupied": "Valeur occupée", "full": "Valeur libre", "custom": "Montant personnalisé"}.get(inputs.get("notary_basis"), "À confirmer")),
        ("Taux notarié indicatif saisi", _pct(inputs.get("notary_rate"))),
        ("Montant notarié personnalisé", _eur(inputs.get("notary_amount"))),
        ("Autres frais d'acquisition", _eur(inputs.get("other_fees"))),
    ])

    new_page("Loyers, fiscalité et financement")
    section("Revenus et coûts d'exploitation")
    pairs([
        ("Loyer mensuel de départ", _eur(inputs.get("rent_monthly"))),
        ("Croissance annuelle des loyers", _pct(inputs.get("rent_growth"))),
        ("Vacance locative", _pct(inputs.get("vacancy_rate"))),
        ("Gestion locative", _pct(inputs.get("management_rate"))),
        ("Taxe foncière annuelle", _eur(inputs.get("property_tax"))),
        ("Autres charges annuelles", _eur(inputs.get("other_charges"))),
        ("Travaux annuels", _eur(inputs.get("annual_works"))),
        ("Assurance annuelle", _eur(inputs.get("insurance"))),
        ("Croissance annuelle des charges", _pct(inputs.get("charges_growth"))),
        ("Rénovation ponctuelle", _eur(inputs.get("renovation"))),
    ])
    section("Crédit")
    pairs([
        ("Montant emprunté", _eur(inputs.get("loan_amount"))),
        ("Durée du crédit", _years(inputs.get("loan_years"))),
        ("Taux annuel du crédit", _pct(inputs.get("loan_rate"))),
        ("Taux annuel d'assurance emprunteur", _pct(inputs.get("loan_insurance_rate"))),
        ("Mensualité personnalisée", _eur(inputs.get("loan_payment_override"))),
        ("Frais de remboursement à la sortie", _eur(inputs.get("loan_exit_fee"))),
    ])
    section("Fiscalité déclarée")
    pairs([
        ("Régime fiscal saisi", inputs.get("regime") or "À confirmer"),
        ("Méthode fiscale", {"income": "Revenu imposable / quotient familial", "tmi": "TMI - approximation"}.get(inputs.get("tax_method"), "À confirmer")),
        ("Revenu imposable du foyer", _eur(inputs.get("taxable_income"))),
        ("TMI saisie", _pct(inputs.get("tmi"))),
        ("Parts / parts de base", f"{_fmt(inputs.get('parts'), 2)} / {_fmt(inputs.get('parts_base'), 2)}"),
        ("Situation familiale", inputs.get("situation") or "À confirmer"),
        ("Plafond du quotient familial", _eur(inputs.get("quotient_cap"))),
        ("Autres revenus locatifs annuels", _eur(inputs.get("other_rent"))),
        ("Charges des autres revenus locatifs", _eur(inputs.get("other_rent_charges"))),
        ("Patrimoine IFI déclaré", _eur(inputs.get("ifi_assets"))),
        ("Amortissement annuel saisi", _eur(inputs.get("amortization"))),
    ])
    if portage:
        story.append(p("Portage : ces paramètres ne qualifient pas les revenus du montage. Une absence d'impôt dans les flux ne prouve pas une exonération ; le net fiscal reste à confirmer.", "warning"))
    elif inputs.get("tax_method") == "tmi" or inputs.get("taxable_income") is None:
        story.append(p("Le recours à la TMI est une approximation. Le calcul de l'impôt réel du foyer nécessite le revenu imposable, les parts et la situation fiscale complète.", "warning"))

    new_page("Annexe annuelle - flux de trésorerie")
    story.append(p("Montants annuels en euros, arrondis à l'euro pour la lecture. Le flux net annuel reprend les encaissements et décaissements du moteur, dont le crédit ; il peut être négatif. Le coût cumulé n'est pas une dette bancaire.", "small"))
    if flows:
        rows = [["Année", "Rente", "Loyers", "Charges", "Fiscalité", "Crédit", "Flux net", "Coût net cumulé"]]
        rows += [[_fmt(row.get("year")), *[_fmt(row.get(key)) for key in ("annuity", "rent", "charges", "tax", "loan", "net_flow", "cumulative_cost")]] for row in flows]
        widths = [45, 60, 60, 61, 59, 59, 72, CONTENT_W - 416]
        table = _table(rows, widths, styles)
        table.setStyle(TableStyle([("TOPPADDING", (0, 1), (-1, -1), 3), ("BOTTOMPADDING", (0, 1), (-1, -1), 3)]))
        story.append(table)
    else:
        story.append(p("Flux annuels absents du résultat : à confirmer."))

    new_page("Annexe annuelle - valeur et dette")
    story.append(p("Montants en euros. La marge reste théorique avant les frais et impôts de cession non inclus. Le capital restant dû est présenté séparément pour apprécier l'effet du financement à la sortie.", "small"))
    if flows:
        rows = [["Année", "Rente mensuelle", "Valeur projetée", "Capital restant dû", "Marge nominale"]]
        rows += [[_fmt(row.get("year")), *[_fmt(row.get(key)) for key in ("annuity_monthly", "property_value", "loan_remaining", "nominal_margin")]] for row in flows]
        table = _table(rows, [45, 101, 116, 115, CONTENT_W - 377], styles)
        table.setStyle(TableStyle([("TOPPADDING", (0, 1), (-1, -1), 3), ("BOTTOMPADDING", (0, 1), (-1, -1), 3)]))
        story.append(table)
    else:
        story.append(p("Trajectoire patrimoniale absente du résultat : à confirmer."))

    new_page("Sources et limites du modèle")
    section("Hypothèses et conventions fournies par le moteur")
    assumptions = result.get("assumptions") or []
    if assumptions:
        for assumption in assumptions:
            story.append(p("• " + str(assumption)))
    else:
        story.append(p("Conventions complémentaires non fournies : à confirmer."))
    section("Données d'annonce / opération")
    source_url = inputs.get("source_url")
    if source_url:
        story.append(p(source_url, "small"))
    else:
        story.append(p("Source de l'annonce non renseignée. Les montants saisis sont des hypothèses utilisateur.", "small"))
    notes = inputs.get("notes")
    if notes:
        section("Notes déclarées")
        story.append(p(notes))
    section("Références")
    sources = result.get("sources") or []
    if sources:
        for source in sources:
            label, url = source.get("label") or "Source", source.get("url")
            source_block = [p(label)]
            if url:
                # Never let untrusted input become paragraph markup. Only safe
                # HTTP(S) URLs become clickable; all others stay visible text.
                if str(url).startswith(("https://", "http://")):
                    source_block.append(Paragraph(f'<link href={quoteattr(str(url))} color="#087F83">{_safe(url)}</link>', styles["small"]))
                else:
                    source_block.append(p(url, "small"))
            story.append(KeepTogether(source_block))
    else:
        story.append(p("Références non fournies dans ce résultat : à confirmer."))
    story.append(p("Les calculs de ce rapport sont ceux du moteur de l'application, selon les données et hypothèses affichées.", "small"))
    story.append(p("Le rapport utilise exclusivement le résultat de simulation transmis. Il ne vérifie pas l'annonce, le titre de propriété, les clauses contractuelles ou le traitement fiscal individuel. Les données restent dans le traitement local de l'application.", "small"))

    output = BytesIO()
    doc = SimpleDocTemplate(
        output, pagesize=A4, rightMargin=MARGIN, leftMargin=MARGIN,
        topMargin=23 * mm, bottomMargin=22 * mm,
        title="Viager Studio - " + str(result.get("name") or inputs.get("name") or "Simulation"),
        author="Viager Studio", subject="Simulation immobilière privée",
        pageCompression=1,
    )
    doc.build(story, onFirstPage=_header, onLaterPages=_header, canvasmaker=_NumberedCanvas)
    return output.getvalue()
