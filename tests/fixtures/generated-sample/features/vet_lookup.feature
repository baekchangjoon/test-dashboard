Feature: Vet lookup

  Scenario: list vets passes
    When I list all vets
    Then the vet response status is 200

  Scenario: wrong expectation fails
    When I list all vets
    Then the vet response status is 404
