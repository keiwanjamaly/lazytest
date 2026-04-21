SAMPLE_CTEST_JSON = """
{
  "kind": "ctestInfo",
  "version": { "major": 1, "minor": 0 },
  "tests": [
    {
      "name": "unit.math.addition",
      "command": ["/tmp/build/unit_tests", "unit.math.addition"],
      "properties": [
        { "name": "LABELS", "value": ["unit", "fast"] },
        { "name": "WORKING_DIRECTORY", "value": "/tmp/build" }
      ]
    },
    {
      "name": "integration.database",
      "command": ["/tmp/build/integration_tests", "integration.database"],
      "properties": [
        { "name": "LABELS", "value": "integration;slow" },
        { "name": "WORKING_DIRECTORY", "value": "/tmp/build/tests" }
      ]
    },
    {
      "name": "misc.no_metadata"
    }
  ]
}
"""
