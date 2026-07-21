/**
 * 状态标签格式化
 */
function formatStatus(status) {
  const map = {
    pending: '待接单',
    in_progress: '处理中',
    submitted: '待审批',
    completed: '已完成',
  };
  return map[status] || status;
}

function formatStatusBadge(status) {
  const map = {
    pending: 'pending',
    in_progress: 'progress',
    submitted: 'submitted',
    completed: 'done',
  };
  return map[status] || '';
}

module.exports = {
  formatStatus,
  formatStatusBadge,
};
