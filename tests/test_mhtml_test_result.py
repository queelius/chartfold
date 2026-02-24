"""Tests for MyChart test-result MHTML parser and adapter."""

import email
import email.mime.multipart
import email.mime.text
import quopri
from pathlib import Path

import pytest

from chartfold.adapters.mhtml_test_result_adapter import (
    _parse_vaf,
    _parser_counts,
    test_result_to_unified as adapt_test_result,
)
from chartfold.db import ChartfoldDB
from chartfold.sources.mhtml_test_result import (
    ParsedTestResult,
    ParsedVariant,
    parse_test_result_mhtml,
)


# --- Fixtures ---


def _make_test_result_mhtml(html_body: str) -> bytes:
    """Build a minimal MHTML file with test-result HTML for testing."""
    msg = email.mime.multipart.MIMEMultipart("related")
    msg["Subject"] = "MyChart - Test Results"
    msg["MIME-Version"] = "1.0"

    html_part = email.mime.text.MIMEText(html_body, "html", "utf-8")
    html_part.replace_header("Content-Transfer-Encoding", "quoted-printable")
    html_bytes = html_body.encode("utf-8")
    html_part.set_payload(quopri.encodestring(html_bytes).decode("ascii"))
    msg.attach(html_part)

    return msg.as_bytes()


_SAMPLE_HTML = """\
<html>
<body>
<h1 class="_PageHeading _readOnlyText _heading">TEMPUS XF</h1>
<div class="_Text _readOnlyText subtitle">Collected on Jul 08, 2025 1:30 PM</div>

<!-- Metadata -->
<div class="OrderMetadataLabelValue">
  <span class="InfoLabel">Authorizing provider:</span>
  <span class="emphasis">Benjamin Tan, MD</span>
</div>
<div class="OrderMetadataLabelValue">
  <span class="InfoLabel">Collection date:</span>
  <span class="emphasis">Jul 08, 2025 1:30 PM</span>
</div>
<div class="OrderMetadataLabelValue">
  <span class="InfoLabel">Specimens:</span>
  <span class="emphasis">Blood</span>
</div>
<div class="OrderMetadataLabelValue">
  <span class="InfoLabel">Result date:</span>
  <span class="emphasis">Jul 15, 2025 12:45 PM</span>
</div>
<div class="OrderMetadataLabelValue">
  <span class="InfoLabel">Result status:</span>
  <span class="emphasis">Final</span>
</div>

<!-- Lab name -->
<div class="_Text _readOnlyText subtlecolor labLine">Resulting lab:</div>
<div class="_Text _readOnlyText emphasis labLine">TEMPUS LAB</div>

<!-- Components: Reason -->
<div class="ComponentCard">
  <div class="ComponentCardHeader">
    <div class="titleSection">
      <h3 class="_PageHeading _readOnlyText _heading componentHeading">Reason for Study</h3>
    </div>
  </div>
  <div class="NonNumericResultComponent">
    <span class="valueLabel">Value</span>
    <span class="value multiLine">To identify mutations</span>
  </div>
</div>

<!-- Components: Description of Ranges -->
<div class="ComponentCard">
  <div class="ComponentCardHeader">
    <div class="titleSection">
      <h3 class="_PageHeading _readOnlyText _heading componentHeading">Description of Ranges of DNA Sequences Examined</h3>
    </div>
  </div>
  <div class="NonNumericResultComponent">
    <span class="valueLabel">Value</span>
    <span class="value multiLine">523 gene liquid biopsy</span>
  </div>
</div>

<!-- Components: Overall Interpretation -->
<div class="ComponentCard">
  <div class="ComponentCardHeader">
    <div class="titleSection">
      <h3 class="_PageHeading _readOnlyText _heading componentHeading">Overall Interpretation</h3>
    </div>
  </div>
  <div class="NonNumericResultComponent">
    <span class="valueLabel">Value</span>
    <span class="value multiLine">inconclusive</span>
  </div>
</div>

<!-- Components: TMB -->
<div class="ComponentCard">
  <div class="ComponentCardHeader">
    <div class="titleSection">
      <h3 class="_PageHeading _readOnlyText _heading componentHeading">Tumor Mutational Burden</h3>
    </div>
    <div>View trendsm/MB</div>
  </div>
  <div class="NonNumericResultComponent">
    <span class="valueLabel">Value</span>
    <span class="value multiLine">2.2</span>
  </div>
</div>

<!-- Components: MSI -->
<div class="ComponentCard">
  <div class="ComponentCardHeader">
    <div class="titleSection">
      <h3 class="_PageHeading _readOnlyText _heading componentHeading">Microsatellite Instability Note</h3>
    </div>
  </div>
  <div class="NonNumericResultComponent">
    <span class="valueLabel">Value</span>
    <span class="value multiLine">MSI-High not detected</span>
  </div>
</div>

<!-- Components: Treatment Implications -->
<div class="ComponentCard">
  <div class="ComponentCardHeader">
    <div class="titleSection">
      <h3 class="_PageHeading _readOnlyText _heading componentHeading">Treatment Implications Note</h3>
    </div>
  </div>
  <div class="NonNumericResultComponent">
    <span class="valueLabel">Value</span>
    <span class="value multiLine">No reportable treatment options found.</span>
  </div>
</div>

<!-- Variants section -->
<h2>Genetic variant results</h2>
<div class="VariantList">
  <ol class="_List _Accordion">
    <li>
      <div class="_AccordionItem">
        <h3 class="accordionHeader">
          <button>
            <div class="contentGroup">
              <div class="textGroup">
                <span class="title">ABCC3 - p.A457T - c.1369G&gt;A Missense variant</span>
                <span class="subtleStyle">Assessment: Detected</span>
              </div>
            </div>
          </button>
        </h3>
        <div class="_ExpandableItem">
          <div class="SingleVariant">
            <div class="VariantSection">
              <div class="LabelledItem">
                <span class="label">Classification:</span>
                <span>Uncertain significance</span>
              </div>
              <div class="LabelledItem">
                <span class="label">Type:</span>
                <span>Simple</span>
              </div>
              <div class="LabelledItem">
                <span class="label">Variant Source:</span>
                <span>Unknown genomic origin</span>
              </div>
              <div class="LabelledItem">
                <span class="label">Variant Allele Fraction:</span>
                <span>53.2%</span>
              </div>
            </div>
            <div class="VariantSection">
              <div class="LabelledItem">
                <span class="label">DNA Change:</span>
                <span>c.1369G&gt;A</span>
              </div>
              <div class="LabelledItem">
                <span class="label">Transcript:</span>
                <span>NM_003786 (RefSeq-T)</span>
              </div>
              <div class="LabelledItem">
                <span class="label">Amino Acid Change:</span>
                <span>p.A457T</span>
              </div>
            </div>
            <div class="VariantSection">
              <div class="LabelledItem">
                <span class="label">Analysis Method:</span>
                <span>Sequencing</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </li>
    <li>
      <div class="_AccordionItem">
        <h3 class="accordionHeader">
          <button>
            <div class="contentGroup">
              <div class="textGroup">
                <span class="title">TP53 - p.C238Y - c.713G&gt;A Missense variant</span>
                <span class="subtleStyle">Assessment: Detected</span>
              </div>
            </div>
          </button>
        </h3>
        <div class="_ExpandableItem">
          <div class="SingleVariant">
            <div class="VariantSection">
              <div class="LabelledItem">
                <span class="label">Classification:</span>
                <span>Pathogenic</span>
              </div>
              <div class="LabelledItem">
                <span class="label">Variant Source:</span>
                <span>Somatic</span>
              </div>
              <div class="LabelledItem">
                <span class="label">Variant Allele Fraction:</span>
                <span>0.7%</span>
              </div>
            </div>
            <div class="VariantSection">
              <div class="LabelledItem">
                <span class="label">DNA Change:</span>
                <span>c.713G&gt;A</span>
              </div>
              <div class="LabelledItem">
                <span class="label">Transcript:</span>
                <span>NM_000546 (RefSeq-T)</span>
              </div>
              <div class="LabelledItem">
                <span class="label">Analysis Method:</span>
                <span>Sequencing</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </li>
  </ol>
</div>

</body>
</html>
"""


@pytest.fixture
def sample_mhtml(tmp_path):
    """Write a sample test-result MHTML to a temp file."""
    mhtml_bytes = _make_test_result_mhtml(_SAMPLE_HTML)
    path = tmp_path / "tempus.mhtml"
    path.write_bytes(mhtml_bytes)
    return str(path)


@pytest.fixture
def sample_parsed():
    """Return a ParsedTestResult built from sample HTML (no file I/O)."""
    from chartfold.sources.mhtml_test_result import _extract_from_html

    result = ParsedTestResult()
    _extract_from_html(_SAMPLE_HTML, result)
    return result


# --- Parser tests ---


class TestTestResultParser:
    def test_parse_test_name(self, sample_parsed):
        assert sample_parsed.test_name == "TEMPUS XF"

    def test_parse_panel(self, sample_parsed):
        assert sample_parsed.panel == "523 gene liquid biopsy"

    def test_parse_provider(self, sample_parsed):
        assert sample_parsed.provider == "Benjamin Tan, MD"

    def test_parse_collection_date(self, sample_parsed):
        assert sample_parsed.collection_date == "2025-07-08"

    def test_parse_result_date(self, sample_parsed):
        assert sample_parsed.result_date == "2025-07-15"

    def test_parse_specimen(self, sample_parsed):
        assert sample_parsed.specimen == "Blood"

    def test_parse_status(self, sample_parsed):
        assert sample_parsed.status == "Final"

    def test_parse_lab_name(self, sample_parsed):
        assert sample_parsed.lab_name == "TEMPUS LAB"

    def test_parse_overall_interpretation(self, sample_parsed):
        assert sample_parsed.overall_interpretation == "inconclusive"

    def test_parse_tmb(self, sample_parsed):
        assert sample_parsed.tmb_value == "2.2"
        assert sample_parsed.tmb_unit == "m/MB"

    def test_parse_msi(self, sample_parsed):
        assert sample_parsed.msi_status == "MSI-High not detected"

    def test_parse_treatment_implications(self, sample_parsed):
        assert sample_parsed.treatment_implications == "No reportable treatment options found."

    def test_parse_reason(self, sample_parsed):
        assert sample_parsed.reason == "To identify mutations"

    def test_parse_variant_count(self, sample_parsed):
        assert len(sample_parsed.variants) == 2

    def test_parse_variant_gene(self, sample_parsed):
        assert sample_parsed.variants[0].gene == "ABCC3"
        assert sample_parsed.variants[1].gene == "TP53"

    def test_parse_variant_dna_change(self, sample_parsed):
        assert sample_parsed.variants[0].dna_change == "c.1369G>A"
        assert sample_parsed.variants[1].dna_change == "c.713G>A"

    def test_parse_variant_protein_change(self, sample_parsed):
        assert sample_parsed.variants[0].protein_change == "p.A457T"
        assert sample_parsed.variants[1].protein_change == "p.C238Y"

    def test_parse_variant_type(self, sample_parsed):
        assert sample_parsed.variants[0].variant_type == "Missense variant"
        assert sample_parsed.variants[1].variant_type == "Missense variant"

    def test_parse_variant_assessment(self, sample_parsed):
        assert sample_parsed.variants[0].assessment == "Detected"

    def test_parse_variant_classification(self, sample_parsed):
        assert sample_parsed.variants[0].classification == "Uncertain significance"
        assert sample_parsed.variants[1].classification == "Pathogenic"

    def test_parse_variant_origin(self, sample_parsed):
        assert sample_parsed.variants[0].variant_origin == "Unknown genomic origin"
        assert sample_parsed.variants[1].variant_origin == "Somatic"

    def test_parse_variant_vaf(self, sample_parsed):
        assert sample_parsed.variants[0].vaf == "53.2%"
        assert sample_parsed.variants[1].vaf == "0.7%"

    def test_parse_variant_transcript(self, sample_parsed):
        assert sample_parsed.variants[0].transcript == "NM_003786"
        assert sample_parsed.variants[1].transcript == "NM_000546"

    def test_parse_variant_analysis_method(self, sample_parsed):
        assert sample_parsed.variants[0].analysis_method == "Sequencing"

    def test_parse_from_mhtml_file(self, sample_mhtml):
        result = parse_test_result_mhtml(sample_mhtml)
        assert result.test_name == "TEMPUS XF"
        assert len(result.variants) == 2

    def test_parse_nonexistent_file(self):
        with pytest.raises(FileNotFoundError):
            parse_test_result_mhtml("/nonexistent/file.mhtml")

    def test_parse_empty_html(self):
        """Empty HTML should produce empty result."""
        from chartfold.sources.mhtml_test_result import _extract_from_html

        result = ParsedTestResult()
        _extract_from_html("<html><body></body></html>", result)
        assert result.test_name == ""
        assert len(result.variants) == 0


# --- Adapter tests ---


class TestVafParsing:
    def test_parse_percentage(self):
        assert _parse_vaf("53.2%") == 53.2

    def test_parse_without_percent(self):
        assert _parse_vaf("19") == 19.0

    def test_parse_decimal(self):
        assert _parse_vaf("0.5%") == 0.5

    def test_parse_empty(self):
        assert _parse_vaf("") is None

    def test_parse_non_numeric(self):
        assert _parse_vaf("N/A") is None


class TestTestResultAdapter:
    def test_creates_tmb_lab_result(self, sample_parsed):
        records = adapt_test_result(sample_parsed)
        tmb = [lr for lr in records.lab_results if "Tumor" in lr.test_name]
        assert len(tmb) == 1
        assert tmb[0].value == "2.2"
        assert tmb[0].value_numeric == 2.2
        assert tmb[0].unit == "m/MB"

    def test_creates_msi_lab_result(self, sample_parsed):
        records = adapt_test_result(sample_parsed)
        msi = [lr for lr in records.lab_results if "Microsatellite" in lr.test_name]
        assert len(msi) == 1
        assert msi[0].value == "MSI-High not detected"
        assert msi[0].value_numeric is None

    def test_creates_interpretation_lab_result(self, sample_parsed):
        records = adapt_test_result(sample_parsed)
        interp = [lr for lr in records.lab_results if "Interpretation" in lr.test_name]
        assert len(interp) == 1
        assert interp[0].value == "inconclusive"

    def test_lab_results_have_panel_name(self, sample_parsed):
        records = adapt_test_result(sample_parsed)
        for lr in records.lab_results:
            assert "TEMPUS XF" in lr.panel_name

    def test_creates_genetic_variants(self, sample_parsed):
        records = adapt_test_result(sample_parsed)
        assert len(records.genetic_variants) == 2

    def test_variant_gene_names(self, sample_parsed):
        records = adapt_test_result(sample_parsed)
        genes = [gv.gene for gv in records.genetic_variants]
        assert "ABCC3" in genes
        assert "TP53" in genes

    def test_variant_vaf_parsed(self, sample_parsed):
        records = adapt_test_result(sample_parsed)
        abcc3 = [gv for gv in records.genetic_variants if gv.gene == "ABCC3"][0]
        assert abcc3.vaf == 53.2

    def test_variant_metadata_fields(self, sample_parsed):
        records = adapt_test_result(sample_parsed)
        gv = records.genetic_variants[0]
        assert gv.test_name == "523 gene liquid biopsy"
        assert gv.specimen == "Blood"
        assert gv.collection_date == "2025-07-08"
        assert gv.result_date == "2025-07-15"
        assert gv.lab_name == "TEMPUS LAB"
        assert gv.provider == "Benjamin Tan, MD"

    def test_source_propagated(self, sample_parsed):
        records = adapt_test_result(sample_parsed, source="custom_source")
        assert records.source == "custom_source"
        for lr in records.lab_results:
            assert lr.source == "custom_source"
        for gv in records.genetic_variants:
            assert gv.source == "custom_source"

    def test_parser_counts_match(self, sample_parsed):
        counts = _parser_counts(sample_parsed)
        records = adapt_test_result(sample_parsed)
        adapter_counts = records.counts()
        assert adapter_counts["lab_results"] == counts["lab_results"]
        assert adapter_counts["genetic_variants"] == counts["genetic_variants"]

    def test_empty_data_produces_empty_records(self):
        data = ParsedTestResult()
        records = adapt_test_result(data)
        assert len(records.lab_results) == 0
        assert len(records.genetic_variants) == 0


# --- DB integration tests ---


class TestTestResultDbIntegration:
    def test_load_and_query(self, tmp_path, sample_parsed):
        db = ChartfoldDB(str(tmp_path / "test.db"))
        db.init_schema()

        records = adapt_test_result(sample_parsed)
        result = db.load_source(records, replace=False)

        assert result["lab_results"] == 3
        assert result["genetic_variants"] == 2

        # Query back
        variants = db.query("SELECT gene, classification, vaf FROM genetic_variants ORDER BY gene")
        assert len(variants) == 2
        assert variants[0]["gene"] == "ABCC3"
        assert variants[0]["vaf"] == 53.2
        assert variants[1]["gene"] == "TP53"

        labs = db.query("SELECT test_name, value FROM lab_results WHERE source='mychart_tempus' ORDER BY test_name")
        assert len(labs) == 3

        db.close()

    def test_upsert_idempotent(self, tmp_path, sample_parsed):
        """Loading the same data twice should skip on second load."""
        db = ChartfoldDB(str(tmp_path / "test.db"))
        db.init_schema()

        records = adapt_test_result(sample_parsed)
        result1 = db.load_source(records, replace=False)
        result2 = db.load_source(records, replace=False)

        assert result2["skipped"] is True

        # DB should have exactly the same counts
        variants = db.query("SELECT COUNT(*) as n FROM genetic_variants")
        assert variants[0]["n"] == 2

        db.close()

    def test_load_log_records_genetic_variants(self, tmp_path, sample_parsed):
        """Load log should include genetic_variants_count."""
        db = ChartfoldDB(str(tmp_path / "test.db"))
        db.init_schema()

        records = adapt_test_result(sample_parsed)
        db.load_source(records, replace=False)

        log = db.query("SELECT genetic_variants_count FROM load_log ORDER BY id DESC LIMIT 1")
        assert log[0]["genetic_variants_count"] == 2

        db.close()

    def test_cross_source_coexistence(self, tmp_path, sample_parsed):
        """Test-result data should coexist with other sources."""
        from chartfold.models import LabResult, UnifiedRecords

        db = ChartfoldDB(str(tmp_path / "test.db"))
        db.init_schema()

        # Load test-result data
        records = adapt_test_result(sample_parsed)
        db.load_source(records, replace=False)

        # Load some other source data
        other = UnifiedRecords(
            source="epic",
            lab_results=[
                LabResult(source="epic", test_name="CEA", value="5.8", value_numeric=5.8, result_date="2025-07-10"),
            ],
        )
        db.load_source(other, replace=False)

        # Both should be present
        all_labs = db.query("SELECT COUNT(*) as n FROM lab_results")
        assert all_labs[0]["n"] == 4  # 3 from tempus + 1 from epic

        variants = db.query("SELECT COUNT(*) as n FROM genetic_variants")
        assert variants[0]["n"] == 2  # Only from tempus

        db.close()

    def test_last_load_counts_includes_genetic_variants(self, tmp_path, sample_parsed):
        """last_load_counts should include genetic_variants."""
        db = ChartfoldDB(str(tmp_path / "test.db"))
        db.init_schema()

        records = adapt_test_result(sample_parsed)
        db.load_source(records, replace=False)

        counts = db.last_load_counts("mychart_tempus")
        assert counts is not None
        assert counts["genetic_variants"] == 2

        db.close()
