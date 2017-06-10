/* eslint-disable no-unused-vars */
import {Map} from 'immutable'
import React from 'react'
import {intlShape, FormattedMessage as _FM} from 'react-intl'


export default function initialize({api, uiComponents}) {
  const {IconFont} = uiComponents

  uiComponents.TimelineStatus = class SpamFilterTimelineStatus extends uiComponents.TimelineStatus {
    static contextTypes = {
      intl: intlShape,
    }

    shouldHideContent() {
      const {status} = this.props
      const {isSpamOpen, isSpamReported} = this.state
      const score = status.getExtended('spamfilter')

      // レポート済Spamはもう表示しない
      if(isSpamReported)
        return true

      if(!score) {
        return false
      }

      if(!(score.get('is_spam') && !isSpamOpen)) {
        return false
      }

      return true
    }

    renderBody() {
      if(!this.shouldHideContent())
        return super.renderBody()

      // hide content
      const {isSpamReported} = this.state
      return (
        <div className="spamfilter-hideContent">
          <span className="spamFilter-attentionMessage">
            <IconFont iconName="attention" />
            <_FM id="spamfilter.label.attention" />
          </span>

          {!isSpamReported &&
          <button
            onClick={this.onClickOpenSpam.bind(this)}
            className="button button--mini button--warning"><_FM id="spamfilter.label.show_toot" /></button>
          }
        </div>
      )
    }

    renderMedia() {
      if(!this.shouldHideContent())
        return super.renderMedia()
    }

    renderActions() {
      if(!this.shouldHideContent())
        return super.renderActions()
    }

    renderActionButtons() {
      const {formatMessage: _} = this.context.intl
      const {status} = this.props
      const {isSpamReported} = this.state
      const buttons = super.renderActionButtons()
      const score = status.getExtended('spamfilter')
      const badScore = score ? score.get('bad_score').toFixed(4) : '---'
      const goodScore = score ? score.get('good_score').toFixed(4) : '---'

      /// 最後のdotの1個前に入れる
      buttons.splice(buttons.length - 1, 0,
        <button
          key="spamButton"
          className=""
          disabled={isSpamReported ? true : false}
          alt={_({id: 'spamfilter.label.report'})}
          title={`${_({id: 'spamfilter.label.report'})}\n${badScore} / ${goodScore}`}
          onClick={this.onClickReportAsSpam.bind(this)}>
          <IconFont iconName="cancel" />
        </button>
      )

      return buttons
    }

    onClickOpenSpam() {
      this.setState({isSpamOpen: true})
    }

    /**
     * 当該トゥートをSpamとして報告する
     */
    onClickReportAsSpam() {
      const {account, status} = this.props
      this.setState({isSpamReported: true})

      // 投げっぱなし
      api.makePluginRequest('POST', 'spamfilter', '/report')
        .send({
          status: status.toJSON(),
          account: account.toJSON(),
        })
        .end()
    }
  }
}
