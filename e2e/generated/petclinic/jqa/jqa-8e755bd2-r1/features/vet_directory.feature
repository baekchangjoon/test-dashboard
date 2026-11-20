Feature: Veterinarian directory API
  Veterinarians can be listed and looked up by id.

  Scenario: List all veterinarians
    When the vet directory is listed
    Then the vet response status is 200
    And the vet directory payload is a JSON document

  Scenario: Fetch a listed veterinarian by id
    Given the vet directory has been listed
    When the first listed vet is fetched by id
    Then the fetched vet matches the first listed vet

  Scenario: Fetching an unknown vet id returns not found
    When an unknown vet id is fetched
    Then the vet response status is 404
