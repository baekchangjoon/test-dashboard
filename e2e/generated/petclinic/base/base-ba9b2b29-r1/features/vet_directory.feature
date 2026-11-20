Feature: Vet directory

  Scenario: Listing vets succeeds
    When the vet directory is requested
    Then the vet directory responds with status 200
