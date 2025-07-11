<template>
  <div class="expense-claim-form">
    <div class="form-header">
      <h2 class="text-2xl font-bold text-gray-900">Submit Expense Claim</h2>
      <p class="text-gray-600 mt-2">Add multiple expense items and submit them together</p>
    </div>

    <div class="form-content mt-6">
      <!-- Organization Selection -->
      <div class="organization-section bg-gray-50 p-4 rounded-lg mb-6">
        <label class="block text-sm font-medium text-gray-700 mb-2">
          Organization Type <span class="text-red-500">*</span>
        </label>
        <select
          v-model="organizationType"
          @change="onOrganizationTypeChange"
          class="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-primary-500"
        >
          <option value="">Select organization type</option>
          <option value="Chapter">Chapter</option>
          <option value="Team">Team</option>
          <option value="National">National</option>
        </select>

        <!-- Chapter Selection -->
        <div v-if="organizationType === 'Chapter'" class="mt-3">
          <label class="block text-sm font-medium text-gray-700 mb-2">
            Chapter <span class="text-red-500">*</span>
          </label>
          <select
            v-model="selectedChapter"
            class="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-primary-500"
          >
            <option value="">Select chapter</option>
            <option v-for="chapter in userChapters" :key="chapter" :value="chapter">
              {{ chapter }}
            </option>
          </select>
        </div>

        <!-- Team Selection -->
        <div v-if="organizationType === 'Team'" class="mt-3">
          <label class="block text-sm font-medium text-gray-700 mb-2">
            Team <span class="text-red-500">*</span>
          </label>
          <select
            v-model="selectedTeam"
            class="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-primary-500"
          >
            <option value="">Select team</option>
            <option v-for="team in userTeams" :key="team" :value="team">
              {{ team }}
            </option>
          </select>
        </div>
      </div>

      <!-- Expense Lines -->
      <div class="expense-lines-section">
        <div class="flex justify-between items-center mb-4">
          <h3 class="text-lg font-semibold text-gray-900">Expense Items</h3>
          <button
            @click="addExpenseLine"
            class="inline-flex items-center px-3 py-2 border border-transparent text-sm font-medium rounded-md text-white bg-primary-600 hover:bg-primary-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-primary-500"
          >
            <svg class="w-4 h-4 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4"></path>
            </svg>
            Add Item
          </button>
        </div>

        <!-- Expense Line Headers -->
        <div class="hidden md:grid md:grid-cols-12 gap-4 mb-2 px-4">
          <div class="col-span-2 text-sm font-medium text-gray-700">Date</div>
          <div class="col-span-2 text-sm font-medium text-gray-700">Category</div>
          <div class="col-span-3 text-sm font-medium text-gray-700">Description</div>
          <div class="col-span-2 text-sm font-medium text-gray-700">Amount (€)</div>
          <div class="col-span-2 text-sm font-medium text-gray-700">Receipt</div>
          <div class="col-span-1"></div>
        </div>

        <!-- Expense Lines -->
        <div class="expense-lines space-y-4">
          <div
            v-for="(line, index) in expenseLines"
            :key="line.id"
            class="expense-line bg-white p-4 rounded-lg border border-gray-200 hover:border-gray-300 transition-colors"
          >
            <div class="grid grid-cols-1 md:grid-cols-12 gap-4">
              <!-- Date -->
              <div class="md:col-span-2">
                <label class="block md:hidden text-sm font-medium text-gray-700 mb-1">Date</label>
                <input
                  type="date"
                  v-model="line.expense_date"
                  :max="today"
                  class="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-primary-500"
                  required
                >
              </div>

              <!-- Category -->
              <div class="md:col-span-2">
                <label class="block md:hidden text-sm font-medium text-gray-700 mb-1">Category</label>
                <select
                  v-model="line.category"
                  class="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-primary-500"
                  required
                >
                  <option value="">Select category</option>
                  <option v-for="cat in expenseCategories" :key="cat" :value="cat">
                    {{ cat }}
                  </option>
                </select>
              </div>

              <!-- Description -->
              <div class="md:col-span-3">
                <label class="block md:hidden text-sm font-medium text-gray-700 mb-1">Description</label>
                <input
                  type="text"
                  v-model="line.description"
                  placeholder="Brief description"
                  class="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-primary-500"
                  required
                >
              </div>

              <!-- Amount -->
              <div class="md:col-span-2">
                <label class="block md:hidden text-sm font-medium text-gray-700 mb-1">Amount (€)</label>
                <input
                  type="number"
                  v-model.number="line.amount"
                  step="0.01"
                  min="0.01"
                  placeholder="0.00"
                  class="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-primary-500"
                  required
                >
              </div>

              <!-- Receipt -->
              <div class="md:col-span-2">
                <label class="block md:hidden text-sm font-medium text-gray-700 mb-1">Receipt</label>
                <div class="relative">
                  <input
                    type="file"
                    :id="`receipt-${line.id}`"
                    @change="handleFileUpload($event, index)"
                    accept="image/*,.pdf"
                    class="hidden"
                  >
                  <label
                    :for="`receipt-${line.id}`"
                    class="w-full px-3 py-2 border border-gray-300 rounded-md cursor-pointer hover:bg-gray-50 text-sm text-gray-600 text-center block"
                  >
                    {{ line.receipt_name || 'Choose file' }}
                  </label>
                </div>
              </div>

              <!-- Delete -->
              <div class="md:col-span-1 flex items-center justify-center">
                <button
                  @click="removeExpenseLine(index)"
                  v-if="expenseLines.length > 1"
                  class="text-red-600 hover:text-red-800 transition-colors"
                  title="Remove item"
                >
                  <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"></path>
                  </svg>
                </button>
              </div>
            </div>

            <!-- Notes (optional) -->
            <div class="mt-3">
              <label class="block text-sm font-medium text-gray-700 mb-1">Notes (optional)</label>
              <textarea
                v-model="line.notes"
                rows="2"
                class="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-primary-500"
                placeholder="Additional details about this expense"
              ></textarea>
            </div>
          </div>
        </div>

        <!-- Total -->
        <div class="mt-6 bg-gray-50 p-4 rounded-lg">
          <div class="flex justify-between items-center">
            <span class="text-lg font-medium text-gray-900">Total</span>
            <span class="text-2xl font-bold text-primary-600">€{{ totalAmount.toFixed(2) }}</span>
          </div>
        </div>
      </div>

      <!-- Actions -->
      <div class="mt-8 flex justify-end space-x-4">
        <button
          @click="clearForm"
          class="px-4 py-2 border border-gray-300 rounded-md text-gray-700 hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-gray-500"
        >
          Clear Form
        </button>
        <button
          @click="submitExpenses"
          :disabled="!isFormValid || isSubmitting"
          class="px-6 py-2 border border-transparent rounded-md text-white bg-primary-600 hover:bg-primary-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-primary-500 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          <span v-if="!isSubmitting">Submit Expenses</span>
          <span v-else class="flex items-center">
            <svg class="animate-spin -ml-1 mr-3 h-5 w-5 text-white" fill="none" viewBox="0 0 24 24">
              <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
              <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
            </svg>
            Submitting...
          </span>
        </button>
      </div>
    </div>

    <!-- Success Message -->
    <div v-if="showSuccess" class="fixed inset-0 flex items-center justify-center z-50">
      <div class="fixed inset-0 bg-gray-500 bg-opacity-75 transition-opacity"></div>
      <div class="bg-white rounded-lg p-6 max-w-sm mx-auto relative z-10">
        <div class="flex items-center justify-center w-12 h-12 mx-auto bg-green-100 rounded-full mb-4">
          <svg class="w-6 h-6 text-green-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"></path>
          </svg>
        </div>
        <h3 class="text-lg font-medium text-gray-900 text-center mb-2">Expenses Submitted!</h3>
        <p class="text-sm text-gray-500 text-center mb-4">{{ successMessage }}</p>
        <div class="flex justify-center">
          <button
            @click="closeSuccessModal"
            class="px-4 py-2 bg-primary-600 text-white rounded-md hover:bg-primary-700"
          >
            OK
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script>
import { ref, computed, onMounted } from 'vue'

export default {
  name: 'ExpenseClaimForm',
  setup() {
    // State
    const organizationType = ref('')
    const selectedChapter = ref('')
    const selectedTeam = ref('')
    const userChapters = ref([])
    const userTeams = ref([])
    const expenseCategories = ref([])
    const expenseLines = ref([])
    const isSubmitting = ref(false)
    const showSuccess = ref(false)
    const successMessage = ref('')

    // Computed
    const today = computed(() => {
      return new Date().toISOString().split('T')[0]
    })

    const totalAmount = computed(() => {
      return expenseLines.value.reduce((sum, line) => sum + (parseFloat(line.amount) || 0), 0)
    })

    const isFormValid = computed(() => {
      // Check organization selection
      if (!organizationType.value) return false
      if (organizationType.value === 'Chapter' && !selectedChapter.value) return false
      if (organizationType.value === 'Team' && !selectedTeam.value) return false

      // Check if we have at least one valid expense line
      if (expenseLines.value.length === 0) return false

      // Check each expense line
      return expenseLines.value.every(line => {
        return line.expense_date &&
               line.category &&
               line.description &&
               line.amount > 0
      })
    })

    // Methods
    const loadUserData = async () => {
      try {
        const response = await frappe.call({
          method: 'verenigingen.api.volunteer.expenses.get_volunteer_expense_context'
        })

        if (response.message) {
          userChapters.value = response.message.user_chapters || []
          userTeams.value = response.message.user_teams || []
          expenseCategories.value = response.message.expense_categories || []

          // Auto-select if user has only one chapter/team
          if (userChapters.value.length === 1) {
            selectedChapter.value = userChapters.value[0]
            organizationType.value = 'Chapter'
          } else if (userTeams.value.length === 1) {
            selectedTeam.value = userTeams.value[0]
            organizationType.value = 'Team'
          }
        }
      } catch (error) {
        frappe.msgprint({
          title: 'Error',
          message: 'Failed to load user data',
          indicator: 'red'
        })
      }
    }

    const createExpenseLine = () => {
      return {
        id: Date.now() + Math.random(),
        expense_date: today.value,
        category: '',
        description: '',
        amount: '',
        notes: '',
        receipt_attachment: null,
        receipt_name: ''
      }
    }

    const addExpenseLine = () => {
      expenseLines.value.push(createExpenseLine())
    }

    const removeExpenseLine = (index) => {
      expenseLines.value.splice(index, 1)
    }

    const handleFileUpload = (event, index) => {
      const file = event.target.files[0]
      if (file) {
        expenseLines.value[index].receipt_name = file.name

        const reader = new FileReader()
        reader.onload = (e) => {
          expenseLines.value[index].receipt_attachment = {
            file_name: file.name,
            file_content: e.target.result.split(',')[1], // Remove data:image/... prefix
            content_type: file.type
          }
        }
        reader.readAsDataURL(file)
      }
    }

    const onOrganizationTypeChange = () => {
      selectedChapter.value = ''
      selectedTeam.value = ''
    }

    const submitExpenses = async () => {
      if (!isFormValid.value) return

      isSubmitting.value = true

      try {
        // Prepare expenses data
        const expenses = expenseLines.value.map(line => ({
          description: line.description,
          amount: parseFloat(line.amount),
          expense_date: line.expense_date,
          organization_type: organizationType.value,
          category: line.category,
          chapter: organizationType.value === 'Chapter' ? selectedChapter.value : null,
          team: organizationType.value === 'Team' ? selectedTeam.value : null,
          notes: line.notes || null,
          receipt_attachment: line.receipt_attachment
        }))

        const response = await frappe.call({
          method: 'verenigingen.api.volunteer.expenses.submit_multiple_expenses',
          args: {
            expenses: expenses
          }
        })

        if (response.message && response.message.success) {
          successMessage.value = `Successfully submitted ${response.message.created_count} expense(s) totaling €${totalAmount.value.toFixed(2)}`
          showSuccess.value = true
          clearForm()
        } else {
          throw new Error(response.message?.error || 'Failed to submit expenses')
        }
      } catch (error) {
        frappe.msgprint({
          title: 'Error',
          message: error.message || 'Failed to submit expenses',
          indicator: 'red'
        })
      } finally {
        isSubmitting.value = false
      }
    }

    const clearForm = () => {
      expenseLines.value = [createExpenseLine()]
      // Keep organization selection if user has only one option
      if (userChapters.value.length > 1 && userTeams.value.length > 1) {
        organizationType.value = ''
        selectedChapter.value = ''
        selectedTeam.value = ''
      }
    }

    const closeSuccessModal = () => {
      showSuccess.value = false
    }

    // Initialize
    onMounted(() => {
      loadUserData()
      expenseLines.value = [createExpenseLine()]
    })

    return {
      organizationType,
      selectedChapter,
      selectedTeam,
      userChapters,
      userTeams,
      expenseCategories,
      expenseLines,
      isSubmitting,
      showSuccess,
      successMessage,
      today,
      totalAmount,
      isFormValid,
      addExpenseLine,
      removeExpenseLine,
      handleFileUpload,
      onOrganizationTypeChange,
      submitExpenses,
      clearForm,
      closeSuccessModal
    }
  }
}
</script>

<style scoped>
.expense-claim-form {
  @apply max-w-6xl mx-auto p-6;
}

.form-header {
  @apply border-b border-gray-200 pb-4;
}

.expense-line {
  @apply transition-all duration-200;
}

.expense-line:hover {
  @apply shadow-md;
}

/* Custom scrollbar for expense lines */
.expense-lines {
  max-height: 600px;
  overflow-y: auto;
}

.expense-lines::-webkit-scrollbar {
  width: 8px;
}

.expense-lines::-webkit-scrollbar-track {
  @apply bg-gray-100 rounded;
}

.expense-lines::-webkit-scrollbar-thumb {
  @apply bg-gray-400 rounded;
}

.expense-lines::-webkit-scrollbar-thumb:hover {
  @apply bg-gray-500;
}
</style>
