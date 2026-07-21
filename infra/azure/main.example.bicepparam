using './main.bicep'

param location = 'westus'
param resourceGroupName = 'rg-thoughtstage-research'
param projectName = 'thoughtstage'
param deployModels = true
param enableBudget = true
param monthlyBudgetAmount = 100

// Replace before deployment. The template refuses to enable a budget with no recipients.
param budgetContactEmails = [
  'replace-me@example.com'
]
