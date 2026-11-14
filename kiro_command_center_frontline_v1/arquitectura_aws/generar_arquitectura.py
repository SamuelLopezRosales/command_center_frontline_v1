from PIL import Image, ImageDraw, ImageFont
S = 2
W, H = 1260, 900
img = Image.new("RGB", (W * S, H * S), "white")
d = ImageDraw.Draw(img)
F = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
FB = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
def f(sz, bold=False): return ImageFont.truetype(FB if bold else F, sz * S)
def P(v): return int(v * S)

def text(x, y, s, sz=13, bold=False, fill="#111827", anchor="la"):
    d.text((P(x), P(y)), s, font=f(sz, bold), fill=fill, anchor=anchor)

def dashed_rect(x1, y1, x2, y2, color="#9CA3AF", title=None, bg=None):
    if bg: d.rounded_rectangle([P(x1), P(y1), P(x2), P(y2)], radius=P(4), fill=bg)
    # dashed border
    def dl(a, b):
        (ax, ay), (bx, by) = a, b
        L = ((bx - ax) ** 2 + (by - ay) ** 2) ** 0.5
        n = int(L // (8 * S)) + 1
        for i in range(0, n, 2):
            t1, t2 = i / n, min((i + 1) / n, 1)
            d.line([(P(ax + (bx - ax) * t1), P(ay + (by - ay) * t1)), (P(ax + (bx - ax) * t2), P(ay + (by - ay) * t2))], fill=color, width=S)
    dl((x1, y1), (x2, y1)); dl((x2, y1), (x2, y2)); dl((x2, y2), (x1, y2)); dl((x1, y2), (x1, y1))
    if title: text(x1 + 6, y1 + 4, title, 12, fill="#374151")

ICON_COL = {"dns": "#8C4FFF", "cdn": "#8C4FFF", "api": "#A166FF", "alb": "#8C4FFF", "auth": "#DD344C",
            "compute": "#ED7100", "db": "#3B48CC", "storage": "#569A31", "queue": "#E7157B",
            "lambda": "#ED7100", "ses": "#DD344C", "sec": "#DD344C", "ops": "#E7157B", "user": "#232F3E", "ext": "#16A34A"}

ICON_DIR = "/sessions/blissful-kind-pascal/mnt/frontline_commandcenter/command-center-v1/arquitectura_de_aws/iconos/"
ICON_FILE = {"53": "route-53.png", "CF": "cloudfront.png", "WAF": "waf.png", "COG": "cognito.png", "API": "api-gateway.png",
             "S3": "simple-storage-service-s3.png", "ALB": "elb-application-load-balancer.png", "ECS": "elastic-container-service.png",
             "FG": "fargate.png", "RDS": "rds.png", "SQS": "simple-queue-service-sqs.png", "SNS": "simple-notification-service-sns.png",
             "EB": "eventbridge.png", "λ": "lambda.png", "SES": "simple-email-service-ses.png", "IAM": "iam.png",
             "KMS": "key-management-service.png", "SM": "secrets-manager.png", "CW": "cloudwatch.png", "CT": "cloudtrail.png",
             "SSM": "systems-manager.png"}

def icon(cx, cy, glyph, kind, label=None, size=44, lab_sz=12, lab_w=None):
    x1, y1 = cx - size / 2, cy - size / 2
    if glyph in ICON_FILE:
        im = Image.open(ICON_DIR + ICON_FILE[glyph]).convert("RGBA").resize((P(size), P(size)), Image.LANCZOS)
        img.paste(im, (P(x1), P(y1)), im)
    else:
        d.rounded_rectangle([P(x1), P(y1), P(x1 + size), P(y1 + size)], radius=P(6), fill=ICON_COL[kind])
        fnt = f(14 if len(glyph) <= 3 else 11, True)
        d.text((P(cx), P(cy)), glyph, font=fnt, fill="white", anchor="mm")
    if label:
        for i, ln in enumerate(label.split("\n")):
            text(cx, cy + size / 2 + 4 + i * 14, ln, lab_sz, anchor="ma", fill="#111827")

def person(cx, cy, label, color="#232F3E"):
    d.ellipse([P(cx - 9), P(cy - 26), P(cx + 9), P(cy - 8)], fill=color)
    d.rounded_rectangle([P(cx - 16), P(cy - 6), P(cx + 16), P(cy + 18)], radius=P(8), fill=color)
    for i, ln in enumerate(label.split("\n")):
        text(cx, cy + 24 + i * 13, ln, 11, anchor="ma")

def arrow(points, color="#1E5AA8", dashed=False, head=True):
    for (a, b), (c, e) in zip(points[:-1], points[1:]):
        pass
    for i in range(len(points) - 1):
        (ax, ay), (bx, by) = points[i], points[i + 1]
        if not dashed:
            d.line([(P(ax), P(ay)), (P(bx), P(by))], fill=color, width=2 * S)
        else:
            L = ((bx - ax) ** 2 + (by - ay) ** 2) ** 0.5
            n = max(int(L // 6), 1)
            for k in range(0, n, 2):
                t1, t2 = k / n, min((k + 1) / n, 1)
                d.line([(P(ax + (bx - ax) * t1), P(ay + (by - ay) * t1)), (P(ax + (bx - ax) * t2), P(ay + (by - ay) * t2))], fill=color, width=2 * S)
    if head:
        (ax, ay), (bx, by) = points[-2], points[-1]
        import math
        ang = math.atan2(by - ay, bx - ax)
        L, Wd = 9, 5
        p1 = (bx - L * math.cos(ang) + Wd * math.sin(ang), by - L * math.sin(ang) - Wd * math.cos(ang))
        p2 = (bx - L * math.cos(ang) - Wd * math.sin(ang), by - L * math.sin(ang) + Wd * math.cos(ang))
        d.polygon([(P(bx), P(by)), (P(p1[0]), P(p1[1])), (P(p2[0]), P(p2[1]))], fill=color)

def yellow(x, y, s):
    w = len(s) * 7.2 + 12
    d.rectangle([P(x), P(y), P(x + w), P(y + 20)], fill="#FFFF00")
    text(x + 6, y + 3, s, 12, bold=True)

# ---------- Título
text(12, 8, "Command Center v1 · Application Architecture", 30, bold=True, fill="#111827")

# ---------- Capa DNS / CDN / Auth / API (columna izquierda)
dashed_rect(12, 60, 150, 200, title="DNS")
icon(81, 130, "53", "dns", "Route 53", size=46)
dashed_rect(170, 60, 320, 200, title="CDN")
icon(245, 105, "CF", "cdn", "CloudFront", size=44)
icon(245, 172, "WAF", "sec", "AWS WAF", size=34, lab_sz=10)
dashed_rect(170, 220, 320, 340, title="Autenticación")
icon(245, 280, "COG", "auth", "Cognito\nRH + MFA", size=46, lab_sz=11)
dashed_rect(170, 360, 320, 520, title="Capa de API")
icon(245, 420, "API", "api", "API Gateway\n/api y /webhook", size=46, lab_sz=11)

# ---------- Usuarios
dashed_rect(12, 560, 150, 720, title="Usuarios")
person(81, 620, "Personal de RH")
person(81, 690, "Colaborador\n(WhatsApp)")

# ---------- Frontend y acceso
dashed_rect(340, 60, 650, 200, title="Frontend")
icon(495, 130, "S3", "storage", "Panel RH (SPA)\n+ verificación QR", size=46, lab_sz=11)
dashed_rect(340, 220, 650, 520, title="Access layer")
icon(495, 420, "ALB", "alb", "Application\nLoad Balancer", size=50, lab_sz=12)

# ---------- Backend ECS
dashed_rect(680, 60, 930, 520, title="Backend")
text(700, 82, "Elastic Container Service", 12, fill="#ED7100", bold=True)
d.rectangle([P(695), P(104), P(915), P(500)], outline="#ED7100", width=2 * S)
svcs = ["Colaboradores\n+ carga masiva", "Campos\ndinámicos", "Constancias\n+ plantillas", "Notificaciones\n+ audiencias", "Dashboard\n+ historial", "WhatsApp\nverificación y chat"]
for i, s_ in enumerate(svcs):
    x = 712
    y = 122 + i * 62
    d.rounded_rectangle([P(x), P(y), P(x + 190), P(y + 46)], radius=P(4), fill="#FFF7ED", outline="#ED7100", width=S)
    ic = Image.open(ICON_DIR + "ecs-container.png").convert("RGBA").resize((P(30), P(30)), Image.LANCZOS)
    img.paste(ic, (P(x + 8), P(y + 8)), ic)
    for j, ln in enumerate(s_.split("\n")):
        text(x + 46, y + 6 + j * 16, ln, 12, bold=(j == 0))

# ---------- Bases y almacenamiento
dashed_rect(960, 60, 1240, 200, title="Bases de datos")
icon(1040, 130, "RDS", "db", "RDS PostgreSQL\nMulti-AZ", size=46, lab_sz=11)
dashed_rect(960, 220, 1240, 520, title="Almacenamiento S3")
icon(1040, 300, "S3", "storage", "Plantillas JSON\n+ logotipos", size=42, lab_sz=11)
icon(1040, 395, "S3", "storage", "Constancias PDF\nObject Lock", size=42, lab_sz=11)
icon(1040, 490, "S3", "storage", "Cargas Excel\n(temporal)", size=42, lab_sz=11)

# ---------- Procesos asíncronos
dashed_rect(680, 560, 930, 740, title="Procesos asíncronos")
icon(730, 620, "SQS", "queue", "Cola PDF", size=40, lab_sz=10)
icon(800, 620, "SQS", "queue", "Cola cargas", size=40, lab_sz=10)
icon(870, 620, "SQS", "queue", "WhatsApp\nentrada / salida", size=40, lab_sz=10)
icon(730, 700, "FG", "compute", "Worker PDF", size=40, lab_sz=10)
icon(800, 700, "FG", "compute", "Worker carga", size=40, lab_sz=10)
icon(870, 700, "EB", "queue", "Envíos\nprogramados", size=40, lab_sz=10)

# ---------- Notificaciones y alertas
dashed_rect(340, 560, 650, 740, title="Notificaciones")
icon(390, 620, "λ", "lambda", "Webhook\nMeta", size=40, lab_sz=10)
icon(460, 620, "λ", "lambda", "Enviador\nWhatsApp", size=40, lab_sz=10)
icon(530, 620, "λ", "lambda", "Estados\nde entrega", size=40, lab_sz=10)
icon(600, 620, "SNS", "queue", "Alertas\na RH", size=40, lab_sz=10)
icon(390, 700, "SES", "ses", "Correo de\nrespaldo", size=40, lab_sz=10)

# ---------- Terceros
dashed_rect(340, 770, 650, 850, title="3rd Party Services")
icon(420, 812, "META", "ext", "Meta WhatsApp Cloud API", size=36, lab_sz=11)

# ---------- Seguridad y operación
dashed_rect(960, 560, 1240, 850, title="Security and Operations")
icon(1000, 625, "IAM", "sec", "IAM", size=40, lab_sz=10)
icon(1070, 625, "KMS", "sec", "KMS\ndatos sensibles", size=40, lab_sz=10)
icon(1140, 625, "SM", "sec", "Secrets\nManager", size=40, lab_sz=10)
icon(1000, 720, "CW", "ops", "CloudWatch", size=40, lab_sz=10)
icon(1070, 720, "CT", "ops", "CloudTrail\nbitácora", size=40, lab_sz=10)
icon(1140, 720, "SSM", "ops", "Systems\nManager", size=40, lab_sz=10)
icon(1000, 800, "RDS", "db", "Backup y\nPITR", size=40, lab_sz=10)

# ---------- Flechas
BLUE = "#1E5AA8"
arrow([(81, 530), (81, 200)], color="#111827", dashed=True)          # DNS request
yellow(88, 332, "DNS Request")
arrow([(120, 620), (190, 620), (190, 105), (223, 105)], color=BLUE)     # web request a CloudFront
yellow(128, 562, "Web Request")
arrow([(268, 105), (340, 105)], color=BLUE)                            # CDN -> frontend
arrow([(120, 690), (182, 690), (182, 420), (222, 420)], color=BLUE)    # usuario -> API
yellow(120, 672, "API Request")
arrow([(268, 420), (468, 420)], color=BLUE)                            # API -> ALB
arrow([(245, 360), (245, 318)], color="#DD344C", dashed=True)         # API <-> Cognito
arrow([(520, 420), (680, 420)], color=BLUE)                            # ALB -> backend
arrow([(930, 130), (960, 130)], color=BLUE)                            # backend -> RDS
arrow([(930, 300), (960, 300)], color=BLUE)                            # backend -> S3
arrow([(805, 520), (805, 560)], color=BLUE)                            # backend -> asíncronos
arrow([(680, 620), (650, 620)], color=BLUE)                            # procesos -> notificaciones
arrow([(420, 770), (420, 740)], color="#16A34A", head=False)
arrow([(460, 650), (430, 770)], color="#16A34A")                       # enviador -> Meta
arrow([(430, 800), (110, 740)], color="#16A34A", dashed=True)          # Meta -> colaborador
yellow(160, 782, "WhatsApp")
img = img.resize((W, H), Image.LANCZOS)
img.save("arquitectura_command_center_v1.png")
print("ok", img.size)
