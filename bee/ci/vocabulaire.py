"""The Bee registry's names, as minizBee reads them (bee/ci/tache.py, bee/ci/verdict.py).

The registry writes English since its switch (ruche-0145): tasks/, tools/, English keys and values. minizBee reads only
those, with one exception: metric ids. The registry still writes them in French until it renames its data (ruche-0149),
so they are read in either vocabulary, one per document, and brought to their English names, the ones minizBee's bench
and plugin write (bee/bench/ab.py, bee/judge/project.py).

A PR's manifest is read in either vocabulary until the registry stops reading French manifests (bee's DATE_D,
2027-01-01): one vocabulary per manifest, brought to English keys. What cannot be read raises Illisible, never a
default value.
"""


class Illisible(ValueError):
    """Data from the registry or the PR that minizBee cannot read: the step fails with this message."""


# The metrics minizBee measures (bee/bench/ab.py, bee/judge/project.py), in their English names: the ones verdict.py can
# judge.
METRIQUES = ["compression_throughput_n1", "compression_throughput_n6", "compression_throughput_n9",
             "decompression_throughput", "ratio_n6", "max_memory_kb"]
# Their French names, as the registry writes them until ruche-0149 renames its data (tools/migration/names.yaml, domain
# metric_id); ratio_n6 and the instruction counts (instructions_n1…) are the same in both.
METRIQUES_FR = {"debit_compression_n1": "compression_throughput_n1", "debit_compression_n6": "compression_throughput_n6",
                "debit_compression_n9": "compression_throughput_n9", "debit_decompression": "decompression_throughput",
                "memoire_max_ko": "max_memory_kb"}
# Enumerated values of a task.
TYPES = ("optimization", "review", "measurement", "test", "split")
SORTIES = ("identical", "may_change")
# Keys of a manifest (the registry's schemas/manifest.schema.json), French -> English, per level; agent, client, machine
# and repetitions are the same in both. « metric » is not in the schema, but verdict.py reads it (local simulation
# without a task).
CLES_MANIFESTE = {"tache": "task", "utilisateur": "user", "resume": "summary", "changement": "change",
                  "mesures": "measurements", "teste": "tested", "non_teste": "untested", "doutes": "doubts",
                  "taille_reelle": "actual_size", "metrique": "metric"}
CLES_AGENT = {"modele": "model"}
CLES_MESURES = {"commande": "command", "avant": "before", "apres": "after"}


def metrique_anglaise(nom):
    """A metric id in its English name (a French id of METRIQUES_FR translated, any other value as it is)."""
    return METRIQUES_FR.get(nom, nom) if isinstance(nom, str) else nom


def vocabulaire_des_metriques(noms, quoi):
    """Refuses a document that names metrics in both vocabularies (Illisible)."""
    francais = sorted(n for n in noms if isinstance(n, str) and n in METRIQUES_FR)
    anglais = sorted(n for n in noms if isinstance(n, str) and n in METRIQUES_FR.values())
    if francais and anglais:
        raise Illisible(f"{quoi} mixes French metric ids ({', '.join(francais)}) and English ones ({', '.join(anglais)}): refused")


def metrique_de_la_tache(donnees):
    """The task's main metric, in its English name: an id of METRIQUES, or None if the task says explicitly that it has
    none (metric: null). Key missing, or metric unknown: Illisible (the verdict never picks its own)."""
    if not isinstance(donnees, dict):
        raise Illisible("the task does not contain a YAML object")
    if "metric" not in donnees:
        raise Illisible("key « metric » missing from the task: metric unreadable")
    if donnees["metric"] is None:
        return None
    metrique = metrique_anglaise(donnees["metric"])
    if not isinstance(metrique, str) or metrique not in METRIQUES:
        raise Illisible(f"metric « {donnees['metric']} » unknown to minizBee (expected: {', '.join(METRIQUES)}, their French "
                        "ids until ruche-0149, or null)")
    return metrique


def valeur(tache, cle, valeurs):
    """An enumerated value of the task; a value outside `valeurs`, or missing: Illisible."""
    v = tache.get(cle)
    if not isinstance(v, str) or v not in valeurs:
        raise Illisible(f"{cle} « {v} » unreadable in the task (expected: {', '.join(sorted(valeurs))})")
    return v


def lire_tache(donnees):
    """type, metric and compressed_output of the task, in English. A missing compressed_output means « identical », the
    strictest check; present, it must be readable. An optimization without a metric (metric: null) is unreadable: R4
    would have nothing to judge."""
    metrique = metrique_de_la_tache(donnees)
    sortie = valeur(donnees, "compressed_output", SORTIES) if "compressed_output" in donnees else "identical"
    type_tache = valeur(donnees, "type", TYPES)
    if type_tache == "optimization" and metrique is None:
        raise Illisible("an optimization task without a metric (metric: null): unreadable, R4 would have nothing to judge")
    return {"type": type_tache, "metric": metrique, "compressed_output": sortie}


def langue(niveaux, quoi):
    """« fr », « en » or None (no key specific to either) for (mapping, map) pairs of one document."""
    francais = sorted(k for d, carte in niveaux for k in d if k in carte)
    anglais = sorted(k for d, carte in niveaux for k in d if k in carte.values())
    if francais and anglais:
        raise Illisible(f"{quoi} mixes both vocabularies (French keys {francais}, English keys {anglais}): refused")
    return "en" if anglais else ("fr" if francais else None)


def en_anglais(d, carte, langue_document):
    return {carte.get(k, k): v for k, v in d.items()} if langue_document == "fr" else dict(d)


def lire_manifeste(donnees):
    """The PR's manifest with English keys, at its three levels; its metric ids in English. Mixed: Illisible."""
    if not isinstance(donnees, dict):
        raise Illisible("the manifest does not contain a YAML object")
    niveaux = [(donnees, CLES_MANIFESTE)]
    niveaux += [(donnees[c], CLES_AGENT) for c in ("agent",) if isinstance(donnees.get(c), dict)]
    niveaux += [(donnees[c], CLES_MESURES) for c in ("mesures", "measurements") if isinstance(donnees.get(c), dict)]
    langue_manifeste = langue(niveaux, "the manifest")
    manifeste = en_anglais(donnees, CLES_MANIFESTE, langue_manifeste)
    for cle, carte in (("agent", CLES_AGENT), ("measurements", CLES_MESURES)):
        if isinstance(manifeste.get(cle), dict):
            manifeste[cle] = en_anglais(manifeste[cle], carte, langue_manifeste)
    mesures = manifeste.get("measurements") if isinstance(manifeste.get("measurements"), dict) else {}
    cotes = [mesures[c] for c in ("before", "after") if isinstance(mesures.get(c), dict)]
    vocabulaire_des_metriques([manifeste.get("metric")] + [n for d in cotes for n in d], "the manifest")
    if "metric" in manifeste:
        manifeste["metric"] = metrique_anglaise(manifeste["metric"])
    for c in ("before", "after"):
        if isinstance(mesures.get(c), dict):
            mesures[c] = {metrique_anglaise(n): v for n, v in mesures[c].items()}
    return manifeste
