# beacon2-import

## What this package does

It does two jobs. It **loads** (writes) Beacon JSON into a self-hosted beacon's
MongoDB database. And it **searches** (reads) one or many beacons: registered
providers over the GA4GH Beacon v2 API, or your own beacon over MongoDB.

## The two commands

<!-- BEGIN GENERATED: commands -->
| Command | Job | Status |
|---|---|---|
| `beacon2-import` | WRITE: load Beacon JSON into a self-hosted beacon's MongoDB | Current, supported. The only way to put data in. |
| `beacon2-query` | READ: search one or many beacons: registered providers over the Beacon v2 API, or your own beacon over MongoDB | Current, supported. The only way to search. Replaces the 2.x beacon2-search command. |
<!-- END GENERATED: commands -->

`beacon2-query` replaces the 2.x `beacon2-search` command, removed in 3.0.0.

## Which command do I want?

- **To load data into your own beacon** use `beacon2-import`.
- **To search anything** (registered providers, your own beacon, or both in
  turn) use `beacon2-query`.

Scripts written for the 2.x `beacon2-search` command need updating: see
[Migrating 2.x beacon2-search scripts](#migrating-2x-beacon2-search-scripts).

## beacon2-query

Subcommands: `range`, `bracket`, `sequence`, `gene`, `cnv`, `entity`,
`service-info` and `filtering-terms`. Positions are 1-based, as in a genome
browser.

### Over the Beacon v2 API

Selects providers from the packaged registry and queries each independently:

```
beacon2-query range --providers org.cancercelllines --variant-class CNV \
    --reference-name 3 --start 195728638 --end 198169247
```

Narrow an API query with `--filter`, which takes ontology terms such as
`ontology:NCIT:C3058:descendants=true`.

### Over your own beacon's MongoDB

```
beacon2-query range --transport mongodb --db-host 127.0.0.1 \
    --database beacon --collection genomicVariations \
    --credentials-file credentials.txt \
    --reference-name 17 --start 7572837 --end 7578641 --variant-type DEL
```

Narrow a MongoDB query with `--field PATH=VALUE`, an exact match on a document
field, e.g. `--field tumorGrade.label=G2`. `--filter` is refused on MongoDB,
because a raw collection has no mapping from ontology terms to fields; `--field`
is refused on the API, which has no field-matching parameter.

The credentials file holds one `key=value` per line: `db_auth_source`,
`db_user` and `db_password`.

### The two output files

- **`results.tsv`**: one row per matching observation, each tagged with the
  beacon and variant class it came from.
- **`outcomes.tsv`**: one row per beacon and variant class, saying what
  happened. A beacon that returned nothing, one that could not be reached, and
  one that does not hold that kind of variant are told apart here.

A result is reported as complete only when the beacon delivered everything it
said matched. Some beacons return a different random subset whenever fewer
than all matches are requested, so `beacon2-query` asks for everything and
checks what arrives; if a beacon will not deliver it all, the query is refused
with how many of how many arrived, rather than a sample being passed off as the
answer.

## beacon2-import

Loads a Beacon JSON file into a collection of a self-hosted beacon's MongoDB,
optionally clearing everything first (`--clearAll`) or one collection
(`--clearColl --removeCollection NAME`):

```
beacon2-import --input_json_file variants.json --db-host 127.0.0.1 \
    --database beacon --collection genomicVariations \
    --advance-connection --db-auth-config credentials.json
```

**Credentials.** `--db-auth-config` is a JSON file with `db_auth_source`,
`db_user` and `db_password`. In Galaxy these come from the user's preferences
`beacon2_account|db_auth_source`, `beacon2_account|db_user` and
`beacon2_account|db_password`. With no user set, `beacon2-import` connects
without authentication and says so; it never falls back to default credentials.

**From a Galaxy history.** `--galaxy --galaxy-url URL --galaxy-key KEY` imports
the JSON datasets of a user's histories instead of a local file. This needs
bioblend: `pip install "beacon2-import[galaxy]"`. The Bioconda package includes
it.

## Migrating 2.x beacon2-search scripts

`beacon2-search` is removed in 3.0.0. Nothing translates a 2.x command
automatically any more, so check these three things in every script:

- **Start positions: add 1. End positions: unchanged.** 2.2.4 passed
  coordinates to MongoDB as stored; `beacon2-query` takes 1-based starts.
- **`-vmin` and `-vmax`.** In 2.2.4, `-vmax` set the *minimum* length and
  `-vmin` the *maximum*. `--variant-min-length` and `--variant-max-length` mean
  what they say. A script that swapped the 2.x flags to work around that must
  swap them back when it moves to the new options.
- **Credentials** go in a file of `key=value` lines (`db_auth_source`,
  `db_user`, `db_password`) passed with `--credentials-file`, not 2.x's JSON.

Scripts not worth migrating can pin `beacon2-import==2.2.4`, which stays on
PyPI and Bioconda.

### Worked examples

<!-- BEGIN GENERATED: search-examples -->
**range**

```
beacon2-search range --database 'beacon' --collection 'genomicVariations' --start '7572836' --end '7578641' --referenceName 'refseq:NC_000017.11' --variantType 'DEL'
```
becomes
```
beacon2-query range --transport mongodb --start '7572837' --end '7578641' --reference-name 'refseq:NC_000017.11' --variant-type 'DEL' --database 'beacon' --collection 'genomicVariations'
```

**bracket**

```
beacon2-search bracket --database 'beacon' --collection 'genomicVariations' --start-minimum '5000000' --start-maximum '7676592' --end-minimum '7669607' --end-maximum '10000000' --referenceName 'refseq:NC_000017.11' --variantType 'DEL'
```
becomes
```
beacon2-query bracket --transport mongodb --start-min '5000001' --start-max '7676593' --end-min '7669607' --end-max '10000000' --reference-name 'refseq:NC_000017.11' --variant-type 'DEL' --database 'beacon' --collection 'genomicVariations'
```

**sequence**

```
beacon2-search sequence --database 'beacon' --collection 'genomicVariations' --alternateBases 'A' --referenceBases 'G' --referenceName 'refseq:NC_000017.11' --start '7577119'
```
becomes
```
beacon2-query sequence --transport mongodb --alternate-bases 'A' --reference-bases 'G' --reference-name 'refseq:NC_000017.11' --start '7577120' --database 'beacon' --collection 'genomicVariations'
```

**cnv**

```
beacon2-search cnv --database 'beacon' --collection 'cnv' --start '243618689' --end '243620819' --chromosome '1' --variantType 'DEL'
```
becomes
```
beacon2-query cnv --transport mongodb --start '243618690' --end '243620819' --reference-name '1' --variant-type 'DEL' --database 'beacon' --collection 'cnv'
```

**runs**

```
beacon2-search runs --database 'beacon' --collection 'runs' --libraryStrategy 'WGS' --platform 'Illumina'
```
becomes
```
beacon2-query entity --transport mongodb --entity run --field 'libraryStrategy=WGS' --field 'platform=Illumina' --database 'beacon' --collection 'runs'
```
<!-- END GENERATED: search-examples -->

### Every 2.x option

The tables below are generated from the 2.2.4 command's own argument
definitions, so they list every option it had.

<!-- BEGIN GENERATED: search-migration -->
### Connection options, every subcommand

| 2.x option (as 2.2.4 wired it) | beacon2-query | Note |
|---|---|---|
| `--db-host`, `-H` | `--db-host` |  |
| `--db-port`, `-P` | `--db-port` |  |
| `--advance-connection`, `-a` | `--credentials-file` | authentication is implied by giving a credentials file |
| `--db-auth-config`, `-A` | `--credentials-file` | key=value lines (db_auth_source, db_user, db_password), not JSON |
| `--database`, `-d` | `--database` |  |
| `--collection`, `-c` | `--collection` |  |

### `beacon2-search sequence` → `beacon2-query sequence --transport mongodb`

| 2.x option (as 2.2.4 wired it) | beacon2-query | Note |
|---|---|---|
| `--alternateBases`, `-ab` | `--alternate-bases` |  |
| `--referenceBases`, `-rb` | `--reference-bases` |  |
| `--referenceName`, `-rn` | `--reference-name` |  |
| `--start`, `-s` | `--start` | 1-based in beacon2-query: add 1 to the 2.x value |
| `--collectionIds`, `-id` | `--biosample-ids` | 2.2.4 passed one string to $in, which MongoDB rejects; now a comma-separated list |

### `beacon2-search range` → `beacon2-query range --transport mongodb`

| 2.x option (as 2.2.4 wired it) | beacon2-query | Note |
|---|---|---|
| `--start`, `-s` | `--start` | 1-based in beacon2-query: add 1 to the 2.x value |
| `--end`, `-e` | `--end` |  |
| `--referenceName`, `-rn` | `--reference-name` |  |
| `--alternateBases`, `-ab` | `--alternate-bases` |  |
| `--variantType`, `-v` | `--variant-type` |  |
| `--aminoacidChange`, `-ac` | `--aminoacid-change` |  |
| `--variantMinLength`, `-vmax` | `--variant-min-length` | 2.2.4 attached -vmax to this option; scripts that swapped -vmin and -vmax to compensate must swap them back |
| `--variantMaxLength`, `-vmin` | `--variant-max-length` | 2.2.4 attached -vmin to this option; scripts that swapped -vmin and -vmax to compensate must swap them back |

### `beacon2-search gene` → `beacon2-query gene --transport mongodb`

| 2.x option (as 2.2.4 wired it) | beacon2-query | Note |
|---|---|---|
| `--geneId`, `-g` | `--gene-id` |  |
| `--alternateBases`, `-ab` | `--alternate-bases` |  |
| `--variantType`, `-v` | `--variant-type` |  |
| `--aminoacidChange`, `-ac` | `--aminoacid-change` |  |
| `--variantMinLength`, `-vmax` | `--variant-min-length` | 2.2.4 attached -vmax to this option; scripts that swapped -vmin and -vmax to compensate must swap them back |
| `--variantMaxLength`, `-vmin` | `--variant-max-length` | 2.2.4 attached -vmin to this option; scripts that swapped -vmin and -vmax to compensate must swap them back |

### `beacon2-search bracket` → `beacon2-query bracket --transport mongodb`

| 2.x option (as 2.2.4 wired it) | beacon2-query | Note |
|---|---|---|
| `--start-minimum`, `-smin` | `--start-min` | 1-based in beacon2-query: add 1 to the 2.x value |
| `--start-maximum`, `-smax` | `--start-max` | 1-based in beacon2-query: add 1 to the 2.x value |
| `--end-minimum`, `-emin` | `--end-min` |  |
| `--end-maximum`, `-emax` | `--end-max` |  |
| `--referenceName`, `-rn` | `--reference-name` |  |
| `--variantType`, `-v` | `--variant-type` |  |

### `beacon2-search analyses` → `beacon2-query entity --transport mongodb --entity analysis`

| 2.x option (as 2.2.4 wired it) | beacon2-query | Note |
|---|---|---|
| `--aligner`, `-al` | `--field 'aligner=VALUE'` |  |
| `--analysisDate`, `-ad` | `--field 'analysisDate=VALUE'` |  |
| `--biosampleId`, `-bi` | `--field 'biosampleId=VALUE'` |  |
| `--identification`, `-id` | `--entity-id` |  |
| `--individualId`, `-ii` | `--field 'individualId=VALUE'` |  |
| `--pipelineName`, `-pn` | `--field 'pipelineName=VALUE'` |  |
| `--pipelineRef`, `-pr` | `--field 'pipelineRef=VALUE'` |  |
| `--runId`, `-ri` | `--field 'runId=VALUE'` |  |
| `--variantCaller`, `-vc` | `--field 'variantCaller=VALUE'` |  |

### `beacon2-search biosamples` → `beacon2-query entity --transport mongodb --entity biosample`

| 2.x option (as 2.2.4 wired it) | beacon2-query | Note |
|---|---|---|
| `--biosampleStatus`, `-bs` | `--field 'biosampleStatus.label=VALUE'` |  |
| `--collectionDate`, `-cd` | `--field 'collectionDate=VALUE'` |  |
| `--collectionMoment`, `-cm` | `--field 'collectionMoment=VALUE'` |  |
| `--identification`, `-id` | `--entity-id` |  |
| `--diagnosticMarkers`, `-dm` | `--field 'diagnosticMarkers.label=VALUE'` | declared but ignored by 2.2.4: never added to its query |
| `--histologicalDiagnosis`, `-hd` | `--field 'histologicalDiagnosis.label=VALUE'` |  |
| `--obtentionProcedure`, `-op` | `--field 'obtentionProcedure.procedureCode.label=VALUE'` |  |
| `--pathologicalStage`, `-ps` | `--field 'pathologicalStage.label=VALUE'` |  |
| `--pathologicalTnmFinding`, `-pf` | `--field 'pathologicalTnmFinding.label=VALUE'` |  |
| `--featureType`, `-ft` | `--field 'phenotypicFeatures.featureType.label=VALUE'` |  |
| `--severity`, `-s` | `--field 'phenotypicFeatures.severity.label=VALUE'` |  |
| `--sampleOriginDetail`, `-sd` | `--field 'sampleOriginDetail.label=VALUE'` |  |
| `--sampleOriginType`, `-so` | `--field 'sampleOriginType.label=VALUE'` |  |
| `--sampleProcessing`, `-sp` | `--field 'sampleProcessing.label=VALUE'` |  |
| `--sampleStorage`, `-ss` | `--field 'sampleStorage.label=VALUE'` |  |
| `--tumorGrade`, `-tg` | `--field 'tumorGrade.label=VALUE'` |  |
| `--tumorProgression`, `-tp` | `--field 'tumorProgression.label=VALUE'` |  |

### `beacon2-search cohorts` → `beacon2-query entity --transport mongodb --entity cohort`

| 2.x option (as 2.2.4 wired it) | beacon2-query | Note |
|---|---|---|
| `--cohortDataTypes`, `-ct` | `--field 'cohortDataTypes.label=VALUE'` |  |
| `--cohortDesign`, `-cd` | `--field 'cohortDesign.label=VALUE'` |  |
| `--cohortSize`, `-cz` | `--field 'cohortSize=VALUE'` |  |
| `--cohortType`, `-t` | `--field 'cohortType=VALUE'` |  |
| `--identification`, `-id` | `--entity-id` |  |
| `--genders`, `-g` | `--field 'inclusionCriteria.genders.label=VALUE'` |  |
| `--name`, `-n` | `--field 'name=VALUE'` |  |

### `beacon2-search datasets` → `beacon2-query entity --transport mongodb --entity dataset`

| 2.x option (as 2.2.4 wired it) | beacon2-query | Note |
|---|---|---|
| `--dataUseConditions`, `-du` | `--field 'dataUseConditions.duoDataUse.label=VALUE'` |  |
| `--ontologyModifiers`, `-om` | `--field 'dataUseConditions.duoDataUse.modifiers.label=VALUE'` |  |
| `--identification`, `-id` | `--entity-id` |  |
| `--name`, `-n` | `--field 'name=VALUE'` |  |

### `beacon2-search individuals` → `beacon2-query entity --transport mongodb --entity individual`

| 2.x option (as 2.2.4 wired it) | beacon2-query | Note |
|---|---|---|
| `--ageGroup`, `-g` | `--field 'diseases.ageOfOnset.ageGroup.label=VALUE'` |  |
| `--diseaseCode`, `-do` | `--field 'diseases.diseaseCode.label=VALUE'` |  |
| `--familyHistory`, `-f` | `--field 'diseases.familyHistory=VALUE'` |  |
| `--severity`, `-se` | `--field 'diseases.severity=VALUE'` |  |
| `--stage`, `-st` | `--field 'diseases.stage=VALUE'` |  |
| `--ethnicity`, `-e` | `--field 'ethnicity.label=VALUE'` |  |
| `--geographicOrigin`, `-go` | `--field 'geographicOrigin.label=VALUE'` |  |
| `--identification`, `-id` | `--entity-id` |  |
| `--assayCode`, `-as` | `--field 'measures.assayCode.label=VALUE'` |  |
| `--sex`, `-s` | `--field 'sex.label=VALUE'` |  |

### `beacon2-search runs` → `beacon2-query entity --transport mongodb --entity run`

| 2.x option (as 2.2.4 wired it) | beacon2-query | Note |
|---|---|---|
| `--identification`, `-id` | `--entity-id` |  |
| `--individualId`, `-ii` | `--field 'individualId=VALUE'` |  |
| `--libraryLayout`, `-ll` | `--field 'libraryLayout=VALUE'` |  |
| `--librarySelection`, `-ls` | `--field 'librarySelection=VALUE'` |  |
| `--librarySource`, `-s` | `--field 'librarySource.label=VALUE'` |  |
| `--libraryStrategy`, `-st` | `--field 'libraryStrategy=VALUE'` |  |
| `--platform`, `-p` | `--field 'platform=VALUE'` |  |
| `--platformModel`, `-pm` | `--field 'platformModel.label=VALUE'` |  |
| `--runDate`, `-r` | `--field 'runDate=VALUE'` |  |

### `beacon2-search cnv` → `beacon2-query cnv --transport mongodb`

| 2.x option (as 2.2.4 wired it) | beacon2-query | Note |
|---|---|---|
| `--variantInternalId`, `-vi` | `--field 'variantInternalId=VALUE'` |  |
| `--analysisId`, `-ai` | `--field 'analysisId=VALUE'` |  |
| `--individualId`, `-ii` | `--field 'individualId=VALUE'` |  |
| `--start`, `-s` | `--start` | 1-based in beacon2-query: add 1 to the 2.x value |
| `--end`, `-e` | `--end` |  |
| `--chromosome`, `-ch` | `--reference-name` |  |
| `--gene`, `-g` | `--field 'gene=VALUE'` |  |
| `--variantType`, `-vt` | `--variant-type` |  |
| `--primarySite`, `-p` | `--field 'primarySite=VALUE'` |  |
| `--diseaseType`, `-dt` | `--field 'diseaseType=VALUE'` |  |
| `--variantStateId`, `-si` | `--field 'variantState.id=VALUE'` |  |
| `--variantState`, `-vs` | `--field 'variantState.label=VALUE'` |  |
| `--sequenceId`, `-sd` | `--field 'definitions.Location.sequenceId=VALUE'` |  |
<!-- END GENERATED: search-migration -->

## Why is the package called beacon2-import?

It began as the import tool. The name stays because renaming it would break the
PyPI project, the Bioconda recipe and every Galaxy tool's requirement pin.

## Licence

MIT, from 3.0.0. Releases up to and including 2.2.4 remain under CC-BY-NC-4.0.
