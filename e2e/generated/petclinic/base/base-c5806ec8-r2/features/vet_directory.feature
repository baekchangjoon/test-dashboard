Feature: Vet directory

  Scenario: List the veterinarians
    When the vet directory client requests the vet list
    Then the vet directory response status is 200
    And the vet directory response body is not empty
