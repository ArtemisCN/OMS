const api = require('../../utils/api');

Page({
  data: {
    exam: null, questions: [], currentIdx: 0, answers: {}, submissionId: null,
    loading: true, submitted: false, result: null, passed: false,
    timerStr: '--:--', timeLimit: 1800, elapsedSeconds: 0,
    answeredCount: 0, isLast: false, showConfirm: false,
    currentQ: null, userAnswer: '', progress: '0', timerStatus: '',
  },
  timerInterval: null,

  onLoad(options) {
    const examId = parseInt(options.exam_id);
    if (!examId) { wx.showToast({ title: '参数错误', icon: 'none' }); return; }
    this.examId = examId;
    this.loadQuestions(examId);
  },

  onUnload() { if (this.timerInterval) clearInterval(this.timerInterval); },

  onHide() {
    if (this.timerInterval) {
      clearInterval(this.timerInterval);
      this.timerInterval = null;
      this._pausedAt = Date.now();
    }
  },
  onShow() {
    if (this._pausedAt && !this.timerInterval && this.data.submissionId) {
      var gap = Math.floor((Date.now() - this._pausedAt) / 1000);
      this.setData({ elapsedSeconds: this.data.elapsedSeconds + gap });
      this.startTimer();
      this._pausedAt = null;
    }
  },

  loadQuestions(examId) {
    this.setData({ loading: true });
    api.get('/exam/' + examId + '/questions')
      .then((res) => {
        var questions = res.questions || [];
        var saved = res.saved_answers || {};
        var answers = {};
        questions.forEach(function(q){ if(saved[String(q.id)]) answers[String(q.id)] = saved[String(q.id)]; });
        this.setData({
          exam: res.exam, questions: questions, submissionId: res.submission_id,
          timeLimit: res.time_limit || 1800,
          elapsedSeconds: res.elapsed_seconds || 0,
          loading: false, currentIdx: 0, answers: answers, answeredCount: 0, isLast: false,
        });
        this.renderQuestion();
        this.startTimer();
      })
      .catch((err) => {
        this.setData({ loading: false });
        wx.showToast({ title: (err && err.error) || '加载失败', icon: 'none' });
        wx.navigateBack();
      });
  },

  renderQuestion() {
    var q = JSON.parse(JSON.stringify(this.data.questions[this.data.currentIdx]));
    if (!q) return;
    var qid = String(q.id);
    var userAns = this.data.answers[qid] || '';
    var total = this.data.questions.length;
    var isLast = this.data.currentIdx === total - 1;
    var self = this;
    var answeredCount = this.data.questions.filter(function(x){ return self.data.answers[String(x.id)]; }).length;

    // 预计算选项选中状态（WXML不支持.split/.indexOf）
    var selSet = {};
    if (userAns) {
      var parts = userAns.split(',');
      for (var i = 0; i < parts.length; i++) selSet[parts[i]] = true;
    }
    (q.options || []).forEach(function(opt){ opt.checked = !!selSet[opt.label]; });

    this.setData({
      currentQ: q, userAnswer: userAns, isLast: isLast, answeredCount: answeredCount,
      progress: ((this.data.currentIdx + 1) / total * 100).toFixed(0),
    });
  },

  startTimer() {
    if (this.timerInterval) clearInterval(this.timerInterval);
    var self = this;
    this.timerInterval = setInterval(function(){
      var es = self.data.elapsedSeconds + 1;
      self.setData({ elapsedSeconds: es });
      var limit = self.data.timeLimit;
      var rem = Math.max(0, limit - es);
      var m = String(Math.floor(rem / 60)).padStart(2, '0');
      var s = String(rem % 60).padStart(2, '0');
      var status = rem < 60 ? 'danger' : (rem < 300 ? 'warning' : '');
      self.setData({ timerStr: m + ':' + s, timerStatus: status });
      if (rem <= 0) { clearInterval(self.timerInterval); self.submitExam(); }
    }, 1000);
  },

  selectAnswer(e) {
    var qid = e.currentTarget.dataset.qid;
    var answer = e.currentTarget.dataset.answer;
    var self = this;
    var q = this.data.questions[this.data.currentIdx];
    if (!q) return;
    var newAnswers = JSON.parse(JSON.stringify(this.data.answers));
    if (q.question_type === 'multi') {
      var current = (newAnswers[qid] || '').split(',').filter(function(x){return x;});
      var idx = current.indexOf(answer);
      if (idx >= 0) current.splice(idx, 1); else current.push(answer);
      newAnswers[qid] = current.join(',');
    } else {
      newAnswers[qid] = answer;
    }
    this.setData({ answers: newAnswers });
    this.saveAnswer(qid, newAnswers[qid]);
    this.renderQuestion();
    if (q.question_type === 'single' || q.question_type === 'judge') {
      setTimeout(function(){ self.nextQuestion(); }, 300);
    }
  },

  onFillInput(e) {
    var qid = e.currentTarget.dataset.qid;
    var value = e.detail.value;
    var newAnswers = JSON.parse(JSON.stringify(this.data.answers));
    newAnswers[qid] = value;
    this.setData({ answers: newAnswers });
    this.saveAnswer(qid, value);
  },

  saveAnswer(qid, val) {
    api.post('/exam/' + this.data.submissionId + '/save_answer', {
      question_id: parseInt(qid), answer: val
    }).catch(function(){});
  },

  prevQuestion() { if (this.data.currentIdx > 0) { this.setData({ currentIdx: this.data.currentIdx - 1 }); this.renderQuestion(); } },
  nextQuestion() { if (this.data.currentIdx < this.data.questions.length - 1) { this.setData({ currentIdx: this.data.currentIdx + 1 }); this.renderQuestion(); } },
  goQuestion(e) { this.setData({ currentIdx: parseInt(e.currentTarget.dataset.idx) }); this.renderQuestion(); },

  showConfirm() { this.setData({ showConfirm: true }); },
  hideConfirm() { this.setData({ showConfirm: false }); },

  submitExam() {
    this.setData({ showConfirm: false, loading: true });
    if (this.timerInterval) clearInterval(this.timerInterval);
    var self = this;
    api.post('/exam/submit', {
      submission_id: this.data.submissionId,
      answers: this.data.answers,
      duration_seconds: this.data.elapsedSeconds,
    })
    .then(function(res){
        var r = res.submission;
        // 预计算WXML无法处理的格式
        var accuracyPct = r.total_possible > 0 ? (r.score / r.total_possible * 100).toFixed(1) : '0.0';
        var durMin = Math.floor(r.duration_seconds / 60);
        var durSec = r.duration_seconds % 60;
        r._accuracyStr = accuracyPct + '%';
        r._durationStr = durMin + '分' + durSec + '秒';
        self.setData({ loading: false, submitted: true, result: r, passed: res.passed });
      })
    .catch(function(err){ self.setData({ loading: false }); wx.showToast({ title: (err && err.error) || '提交失败', icon: 'none' }); });
  },

  backToList() { wx.navigateBack(); }
});
