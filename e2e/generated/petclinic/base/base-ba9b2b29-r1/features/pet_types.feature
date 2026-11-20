Feature: Pet types catalogue

  Scenario: Listing pet types succeeds
    When the pet types are requested
    Then the pet types request responds with status 200 and a body
