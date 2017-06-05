/* eslint-disable no-unused-vars */
import {Map} from 'immutable'
import React from 'react'
import {FormattedMessage as _FM} from 'react-intl'


export default function initialize({api, uiComponents}) {
  const {IconFont} = uiComponents

  uiComponents.TimelineStatus = class ExtendedTimelineStatus extends uiComponents.TimelineStatus {
    shouldHideContent() {
      const {status} = this.props
      const {isSpamOpen} = this.state
      const score = status.getExtended('spamfilter')

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
      return (
        <div className="spamfilter-hideContent">
          <span className="spamFilter-attentionMessage">
            <IconFont iconName="attention" />
            <_FM id="spamfilter.label.attention" />
          </span>

          <button
            onClick={this.onClickOpenSpam.bind(this)}
            className="button button--mini button--warning"><_FM id="spamfilter.label.show_toot" /></button>
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

    onClickOpenSpam() {
      this.setState({isSpamOpen: true})
    }

    renderStatusMenuItems() {
      const {status} = this.props
      const score = status.getExtended('spamfilter')
      const menus = super.renderStatusMenuItems()

      if(!score) {
        return menus
      }

      const {isSpamReported} = this.state
      const badScore = score.get('bad_score')
      const isSpam = score.get('is_spam')

      menus.push(
        {
          weight: 0,
          content: (
            <li className="menuItem--spamfilter" key="spamfilter">
              <h4>SpamFilter</h4>
              <div className="menuItem--spamfilter-spamScore">
                <span>Score: {badScore.toFixed(4)}</span>
                {!isSpam &&
                  <button
                    onClick={this.onClickReportAsSpam.bind(this)}
                    disabled={isSpamReported ? true : false}
                    className="button button--mini"><_FM id="spamfilter.label.report" /></button>}
              </div>
            </li>
          )
        },
      )

      return menus
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
          ...status.toJSON(),
          account: account.toJSON(),
        })
        .end()
    }
  }
}
