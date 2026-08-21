# Instree — guide agents

OSINT Instagram mutuels — desktop + web.

## Layout

```
instree/
├── instree/           # package Python (core/, desktop/, web/)
├── bin/               # run-desktop, run-web
├── deploy/pi/         # deploy Paramiko → Raspberry Pi :1488
├── scripts/           # outils dev
├── var/web/           # runtime web (gitignoré)
└── var/desktop/       # runtime desktop (gitignoré)
```

| | Desktop | Web |
|---|---------|-----|
| Lancer | `./bin/run-desktop` | `./bin/run-web` |
| CLI | `instree serve` | `instree-web` |
| Données | `var/desktop/` | `var/web/` ou `INSTREE_HOME` |

## Lancer

```bash
./bin/run-desktop          # desktop local
./bin/run-web              # web local
python3 deploy/pi/deploy_paramiko.py   # deploy Pi (PI_PASS requis)
```

## Secrets

- `PI_PASS` via `scripts/secrets.env` ou export (pas de default dans les scripts)
- `var/web/secret.key`, cookies, DB — jamais versionnés

## Pi

Service `instree-web` — port **1488**, données `/var/lib/instree`.

Voir [`deploy/pi/README.md`](deploy/pi/README.md).
